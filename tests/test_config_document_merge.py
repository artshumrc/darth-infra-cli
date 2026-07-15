"""Semantic diff, reversion, transactions, and three-way merge (ticket 03).

These tests extend the document-editing session with:

* semantic change classification (added / removed / changed / reset-to-default),
* field / section / whole-session reversion that restores baseline value,
  presence, and attached comments,
* draft transactions that group a cascading edit into one reversible unit, and
* conflict-aware three-way merge of the loaded baseline, the current disk
  document, and the in-memory draft.

They stay behind the :class:`ProjectDocument` interface (plus the pure
``diff_documents`` / ``three_way_merge`` helpers) so later UI slices inherit the
same semantics without Textual.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from darth_infra.config.document import (
    ABSENT,
    ChangeOperation,
    ProjectDocument,
    diff_documents,
    three_way_merge,
)
from darth_infra.config.loader import load_config

# Hand-formatted source with comments, two services (one with a trailing
# comment), project tags, and an env override, exercising records and maps.
BASE = """\
#:schema ./darth-infra.schema.json
# Demo project config. Comments and ordering must survive edits and merges.

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
desired_count = 2  # two tasks for HA

# The background worker
[[services]]
name = "worker"
cpu = 128
memory_mib = 256

[environments.prod]
instance_type_override = "db.t4g.small"
"""


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(BASE)
    return path


def _change_for(changes, path):
    for change in changes:
        if change.path == path:
            return change
    raise AssertionError(f"no semantic change at {path!r}; got {[c.path for c in changes]}")


# ---------------------------------------------------------------------------
# Semantic change classification
# ---------------------------------------------------------------------------


def test_setting_an_omitted_field_reports_added(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].command", "run web")

    change = _change_for(doc.semantic_changes(), "services[name=web].command")
    assert change.operation == ChangeOperation.ADDED
    assert change.operation == "added"
    assert change.before is ABSENT
    assert change.after == "run web"


def test_changing_an_explicit_field_reports_changed(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 512)

    change = _change_for(doc.semantic_changes(), "services[name=web].cpu")
    assert change.operation == ChangeOperation.CHANGED
    assert change.before == 256
    assert change.after == 512


def test_resetting_an_explicit_field_reports_reset_to_default(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.reset("services[0].cpu")

    change = _change_for(doc.semantic_changes(), "services[name=web].cpu")
    assert change.operation == ChangeOperation.RESET_TO_DEFAULT
    assert change.before == 256
    # After a reset the effective value falls back to the loader default.
    assert change.after == 256


def test_removing_a_record_reports_a_single_removed_change(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    # Deleting the worker record removes the whole array element.
    doc.reset("services[1]")

    changes = doc.semantic_changes()
    worker_changes = [c for c in changes if c.path.startswith("services[name=worker]")]
    assert len(worker_changes) == 1
    change = worker_changes[0]
    assert change.operation == ChangeOperation.REMOVED
    assert change.path == "services[name=worker]"
    assert change.after is ABSENT
    # The before value carries the removed record for the UI to summarize.
    assert change.before["cpu"] == 128


def test_removing_a_map_entry_reports_removed_not_reset(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.reset("project.tags.owner")

    change = _change_for(doc.semantic_changes(), "project.tags.owner")
    assert change.operation == ChangeOperation.REMOVED
    assert change.before == "platform"
    assert change.after is ABSENT


def test_collection_reorder_produces_no_false_changes() -> None:
    reordered = BASE.replace(
        """\
# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
memory_mib = 512
desired_count = 2  # two tasks for HA

# The background worker
[[services]]
name = "worker"
cpu = 128
memory_mib = 256
""",
        """\
# The background worker
[[services]]
name = "worker"
cpu = 128
memory_mib = 256

# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
memory_mib = 512
desired_count = 2  # two tasks for HA
""",
    )
    assert reordered != BASE
    assert diff_documents(BASE, reordered) == []


# ---------------------------------------------------------------------------
# Reversion (field / section / whole session)
# ---------------------------------------------------------------------------


def test_revert_field_restores_value_and_attached_comment(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].desired_count", 9)
    assert doc.value("services[0].desired_count") == 9

    doc.revert_field("services[0].desired_count")

    assert doc.value("services[0].desired_count") == 2
    # The comment attached to the restored field survives.
    assert "# two tasks for HA" in doc.to_toml()
    assert doc.semantic_changes() == []


def test_revert_field_restores_omitted_presence(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].command", "run")
    assert doc.is_explicit("services[0].command") is True

    doc.revert_field("services[0].command")

    # Baseline omitted the field, so reverting must restore omission, not a
    # written default.
    assert doc.is_explicit("services[0].command") is False
    assert doc.semantic_changes() == []


def test_revert_section_restores_all_fields_in_a_record(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 1024)
    doc.set("services[0].memory_mib", 2048)
    doc.set("services[0].command", "override")

    doc.revert_section("services[0]")

    assert doc.value("services[0].cpu") == 256
    assert doc.value("services[0].memory_mib") == 512
    assert doc.is_explicit("services[0].command") is False
    assert doc.semantic_changes() == []


def test_revert_all_restores_the_whole_session_baseline(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 1024)
    doc.set("project.aws_region", "eu-west-1")
    doc.reset("project.tags.owner")

    doc.revert_all()

    assert doc.to_toml() == BASE
    assert doc.semantic_changes() == []


# ---------------------------------------------------------------------------
# Draft transactions (cascading edits as one reversible unit)
# ---------------------------------------------------------------------------


def test_transaction_groups_edits_and_reverts_them_together(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)

    with doc.transaction() as txn:
        doc.set("services[0].cpu", 512)
        doc.set("alb.domain", "cluster.example.com")
        doc.set("alb.default_target_service", "web")
        doc.reset("services[1]")

    # All edits are applied after the transaction commits.
    assert doc.value("services[0].cpu") == 512
    assert doc.value("alb.domain") == "cluster.example.com"
    assert len(doc.config.services) == 1

    # Reverting the transaction restores every change at once.
    txn.revert()
    assert doc.value("services[0].cpu") == 256
    assert doc.value("alb.domain") is None
    assert doc.value("alb.default_target_service") is None
    assert len(doc.config.services) == 2
    assert doc.semantic_changes() == []


def test_transaction_rolls_back_atomically_on_error(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)

    with pytest.raises(RuntimeError):
        with doc.transaction():
            doc.set("services[0].cpu", 512)
            doc.set("alb.domain", "cluster.example.com")
            raise RuntimeError("cascade failed")

    # A failed cascade leaves no partial changes behind.
    assert doc.value("services[0].cpu") == 256
    assert doc.value("alb.domain") is None
    assert doc.semantic_changes() == []


def test_transaction_preserves_edits_made_before_it(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].memory_mib", 4096)

    with doc.transaction() as txn:
        doc.set("services[0].cpu", 512)

    txn.revert()
    # The pre-transaction edit is untouched by reverting the transaction.
    assert doc.value("services[0].memory_mib") == 4096
    assert doc.value("services[0].cpu") == 256


# ---------------------------------------------------------------------------
# Three-way merge
# ---------------------------------------------------------------------------


def test_disjoint_disk_and_draft_edits_merge_preserving_both_comments(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)
    # Draft edits the web service CPU.
    doc.set("services[0].cpu", 512)

    # Someone else edits the region on disk and adds a comment there.
    disk = BASE.replace(
        'aws_region = "us-east-1"',
        '# region moved for DR\naws_region = "eu-west-1"',
    )
    config_path.write_text(disk)

    result = doc.merge_with_disk()
    assert result.ok
    assert result.conflicts == []

    doc.adopt_merge(result)
    new_revision = doc.save()
    assert new_revision

    reloaded = load_config(config_path)
    # Both disjoint edits are present.
    assert reloaded.services[0].cpu == 512
    assert reloaded.aws_region == "eu-west-1"

    saved = config_path.read_text()
    # Comments from both the draft baseline and the external edit survive.
    assert "# The main web service" in saved
    assert "# region moved for DR" in saved
    assert "# two tasks for HA" in saved


def test_draft_added_record_merges_with_disjoint_disk_edit() -> None:
    # Draft appends a whole new service (with its own comment); disk edits the
    # region. Both changes are disjoint and merge cleanly, and the new record's
    # formatting is preserved via splicing rather than field-by-field rebuild.
    draft = BASE + """
[[services]]
name = "cache"
image = "redis:7-alpine"  # pinned cache image
"""
    disk = BASE.replace('aws_region = "us-east-1"', 'aws_region = "eu-west-1"')

    result = three_way_merge(BASE, disk, draft)
    assert result.ok, result.conflicts

    merged = tomlkit.parse(result.merged_text).unwrap()
    names = [s["name"] for s in merged["services"]]
    assert names == ["web", "worker", "cache"]
    assert merged["project"]["aws_region"] == "eu-west-1"
    # The spliced record keeps the comments attached to its own fields.
    assert "# pinned cache image" in result.merged_text


def test_same_field_edits_report_a_conflict(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 512)

    disk = BASE.replace("cpu = 256", "cpu = 999")
    config_path.write_text(disk)

    result = doc.merge_with_disk()
    assert not result.ok
    assert result.merged_text is None
    conflict = result.conflicts[0]
    assert conflict.path == "services[name=web].cpu"
    assert conflict.baseline == 256
    assert conflict.disk == 999
    assert conflict.draft == 512


def test_delete_versus_modify_reports_a_conflict(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    # Draft deletes the worker record entirely.
    doc.reset("services[1]")

    # Disk modifies a field of the same record.
    disk = BASE.replace(
        """\
[[services]]
name = "worker"
cpu = 128""",
        """\
[[services]]
name = "worker"
cpu = 999""",
    )
    config_path.write_text(disk)

    result = doc.merge_with_disk()
    assert not result.ok
    conflict = _change_for(result.conflicts, "services[name=worker].cpu")
    assert conflict.baseline == 128
    assert conflict.disk == 999
    assert conflict.draft is ABSENT


def test_conflict_detection_does_not_mutate_the_draft(config_path: Path) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 512)
    draft_before = doc.to_toml()

    disk = BASE.replace("cpu = 256", "cpu = 999")
    config_path.write_text(disk)

    result = doc.merge_with_disk()
    assert not result.ok

    # The draft is untouched by the failed merge.
    assert doc.to_toml() == draft_before
    assert doc.value("services[0].cpu") == 512
    with pytest.raises(ValueError):
        doc.adopt_merge(result)


def test_merged_validation_failure_is_reported_and_draft_preserved(
    config_path: Path,
) -> None:
    doc = ProjectDocument.load(config_path)
    doc.set("services[0].cpu", 512)
    draft_before = doc.to_toml()

    # Disk drops the required prod environment; disjoint from the draft edit, so
    # there is no field conflict, but the merged result fails model validation.
    disk = BASE.replace('environments = ["prod"]', 'environments = ["staging"]')
    config_path.write_text(disk)

    result = doc.merge_with_disk()
    assert result.conflicts == []
    assert not result.ok
    assert result.validation is not None and not result.validation.ok

    with pytest.raises(Exception):
        doc.adopt_merge(result)
    # The draft still holds the operator's work.
    assert doc.to_toml() == draft_before


def test_three_way_merge_is_pure_and_text_based() -> None:
    disk = BASE.replace('aws_region = "us-east-1"', 'aws_region = "eu-west-1"')
    draft = BASE.replace("cpu = 256", "cpu = 512")

    result = three_way_merge(BASE, disk, draft)
    assert result.ok
    assert 'aws_region = "eu-west-1"' in result.merged_text
    assert "cpu = 512" in result.merged_text


def test_resolutions_fold_a_conflict_into_a_clean_merge(config_path: Path) -> None:
    # A true same-field conflict, resolved per the caller's per-path choice.
    disk = BASE.replace("cpu = 256", "cpu = 999")

    for choice, expected in (("draft", 512), ("disk", 999)):
        config_path.write_text(BASE)
        doc = ProjectDocument.load(config_path)
        doc.set("services[0].cpu", 512)
        config_path.write_text(disk)

        conflicted = doc.merge_with_disk()
        assert conflicted.conflicts and conflicted.merged_text is None

        resolved = doc.merge_with_disk(
            resolutions={"services[name=web].cpu": choice}
        )
        assert resolved.ok, resolved.conflicts
        # Resolution never mutates the draft until it is adopted.
        assert doc.value("services[0].cpu") == 512
        doc.adopt_merge(resolved)
        assert doc.value("services[0].cpu") == expected
