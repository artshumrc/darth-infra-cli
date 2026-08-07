"""Document-preserving editing contract for the Guided editor (ticket 02).

These tests exercise the small :class:`ProjectDocument` interface that lets the
editor load an existing hand-formatted TOML document, inspect effective versus
explicit values, apply semantic field edits, reset fields to omission, validate
through the existing loader/model semantics, preview the exact patch, and save
without rewriting unrelated document content.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from darth_infra.config.document import (
    DocumentConflictError,
    DocumentValidationError,
    ProjectDocument,
)
from darth_infra.config.loader import load_config

# Hand-formatted source: comments, deliberate ordering, an explicit value equal
# to its default (``cpu = 256``), and many omitted defaults.
HAND_FORMATTED = """\
#:schema ./darth-infra.schema.json
#
# darth-infra config for the demo project.
# These comments and this ordering must survive a one-field edit.
#

[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod"]

# Extra tags for every resource
[project.tags]
owner = "platform"

# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
memory_mib = 512
desired_count = 2
"""


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(HAND_FORMATTED)
    return path


def _changed_lines(before: str, after: str) -> list[str]:
    """Return added/removed lines (with +/- prefix) between two documents."""
    diff = difflib.ndiff(before.splitlines(), after.splitlines())
    return [line for line in diff if line.startswith(("+ ", "- "))]


def test_load_exposes_effective_config(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    assert doc.config.project_name == "demo"
    assert doc.config.services[0].name == "web"


def test_single_edit_preserves_comments_ordering_and_formatting(
    config_path: Path,
) -> None:
    original = config_path.read_text()
    doc = ProjectDocument.load(config_path)

    doc.set("services[0].desired_count", 3)
    doc.save()

    saved = config_path.read_text()
    # Comments survive verbatim.
    assert "# darth-infra config for the demo project." in saved
    assert "# The main web service" in saved
    assert "# Extra tags for every resource" in saved
    # Ordering of unrelated keys is untouched.
    assert saved.index('name = "demo"') < saved.index("aws_region")
    assert saved.index('[[services]]') < saved.index("desired_count")
    # Only the edited line differs from the original.
    changes = _changed_lines(original, saved)
    assert changes == ["- desired_count = 2", "+ desired_count = 3"]
    # And the change round-trips through the canonical loader.
    assert load_config(config_path).services[0].desired_count == 3


def test_omitted_and_explicit_default_share_value_but_differ_in_presence(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)

    # An explicit value equal to its default is present and explicit.
    assert doc.value("services[0].cpu") == 256
    assert doc.is_explicit("services[0].cpu") is True

    # An omitted field reports the effective default but is not explicit.
    assert doc.value("services[0].health_check_timeout_seconds") == 5
    assert doc.is_explicit("services[0].health_check_timeout_seconds") is False

    # Persisting the omitted field at its default value keeps the effective
    # value identical but flips presence to explicit.
    doc.set("services[0].health_check_timeout_seconds", 5)
    assert doc.value("services[0].health_check_timeout_seconds") == 5
    assert doc.is_explicit("services[0].health_check_timeout_seconds") is True


def test_port_default_reflects_loader_semantics_not_dataclass_default(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)
    # ``services[].port`` is omitted-by-loader (None) rather than the dataclass
    # default of 8000. Reading the effective value must follow the loader.
    doc.reset("services[0].port")
    assert doc.is_explicit("services[0].port") is False
    assert doc.value("services[0].port") is None


def test_reset_removes_persisted_key_and_restores_default(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    assert doc.is_explicit("services[0].cpu") is True

    doc.reset("services[0].cpu")

    assert doc.is_explicit("services[0].cpu") is False
    # Effective value falls back to the loader default, not the persisted 256.
    assert doc.value("services[0].cpu") == 256

    doc.save()
    saved = config_path.read_text()
    assert "cpu = 256" not in saved
    # Reset writes omission, not the current default value.
    assert "cpu" not in saved.split("[[services]]", 1)[1]
    assert load_config(config_path).services[0].cpu == 256


def test_invalid_edit_reports_validation_error_and_is_not_written(
    config_path: Path,
) -> None:
    original = config_path.read_text()
    doc = ProjectDocument.load(config_path)

    # 'prod' is required in environments; removing it is a model violation.
    doc.set("project.environments", ["staging"])

    result = doc.validate()
    assert result.ok is False
    assert result.error and "prod" in result.error

    with pytest.raises(DocumentValidationError):
        doc.save()

    # The invalid draft is never written to disk.
    assert config_path.read_text() == original


def test_save_against_changed_disk_revision_refuses_to_overwrite(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].desired_count", 4)

    # Someone else edits the file after we loaded it.
    external = HAND_FORMATTED.replace('aws_region = "us-east-1"', 'aws_region = "eu-west-1"')
    config_path.write_text(external)

    with pytest.raises(DocumentConflictError):
        doc.save()

    # The newer on-disk file is left intact.
    assert config_path.read_text() == external


def test_successful_save_updates_revision_and_reloads(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    before = doc.revision
    assert doc.revision == before  # revision is stable across reads

    doc.set("services[0].cpu", 512)
    # A valid edit does not change the stored revision until saved.
    assert doc.revision == before

    new_revision = doc.save()
    assert new_revision != before
    assert doc.revision == new_revision

    reloaded = load_config(config_path)
    assert reloaded.services[0].cpu == 512

    # A subsequent save with the (now-current) revision succeeds.
    doc.set("services[0].cpu", 1024)
    doc.save()
    assert load_config(config_path).services[0].cpu == 1024


def test_save_leaves_no_temporary_files_behind(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 512)
    doc.save()
    siblings = list(config_path.parent.iterdir())
    assert siblings == [config_path]


def test_toml_patch_shows_only_the_edited_region(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    assert doc.toml_patch() == ""

    doc.set("services[0].desired_count", 7)
    patch = doc.toml_patch()

    assert "-desired_count = 2" in patch
    assert "+desired_count = 7" in patch
    # Unrelated lines never appear as changes in the patch.
    assert "-name = \"demo\"" not in patch
    assert "-aws_region" not in patch


def test_enum_values_are_returned_unwrapped(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    assert doc.value("alb.mode") == "shared"


def test_config_is_inspectable_but_raises_on_invalid_draft(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("project.environments", ["staging"])
    # Raw presence remains inspectable even while the draft is invalid.
    assert doc.is_explicit("project.environments") is True
    with pytest.raises(ValueError):
        _ = doc.config


def test_add_record_appends_minimal_record_and_returns_index(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)
    assert doc.record_count("services") == 1

    index = doc.add_record("services", {"name": "worker"})

    assert index == 1
    assert doc.record_count("services") == 2
    assert doc.value("services[1].name") == "worker"
    # Only the provided key is explicit; every other field stays omitted.
    assert doc.is_explicit("services[1].name") is True
    assert doc.is_explicit("services[1].cpu") is False
    # The new record round-trips through the loader.
    assert [s.name for s in load_config_via_save(doc, config_path)] == ["web", "worker"]


def test_add_record_creates_absent_collection() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "darth-infra.toml"
        path.write_text(
            '[project]\nname = "demo"\nenvironments = ["prod"]\n\n'
            '[[services]]\nname = "web"\n'
        )
        doc = ProjectDocument.load(path)
        assert doc.record_count("s3_buckets") == 0
        index = doc.add_record("s3_buckets", {"name": "media"})
        assert index == 0
        assert doc.record_count("s3_buckets") == 1
        assert doc.value("s3_buckets[0].name") == "media"


def test_raw_record_returns_only_explicit_keys(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    raw = doc.raw_record("services", 0)
    assert raw["name"] == "web"
    assert raw["cpu"] == 256
    # An omitted default is absent from the raw record.
    assert "health_check_timeout_seconds" not in raw
    # It is a detached copy.
    raw["name"] = "mutated"
    assert doc.value("services[0].name") == "web"


def test_remove_record_deletes_and_reindexes(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.add_record("services", {"name": "worker"})
    assert doc.record_count("services") == 2
    doc.remove_record("services", 0)
    assert doc.record_count("services") == 1
    assert doc.value("services[0].name") == "worker"
    # Out-of-range and missing collections are no-ops.
    doc.remove_record("services", 5)
    doc.remove_record("s3_buckets", 0)
    assert doc.record_count("services") == 1


def load_config_via_save(doc: ProjectDocument, path: Path):
    doc.save()
    return load_config(path).services
