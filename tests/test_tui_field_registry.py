"""Schema-coverage contract for the Guided editor field registry.

These tests enforce that the persisted configuration schema is the completeness
boundary for the editor: every user-authored field has a registered control, the
packaged and root schema copies stay identical, CLI-maintained metadata is
explicitly read-only, and runtime-only state never leaks into editable coverage.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from darth_infra.tui.field_registry import (
    FIELD_REGISTRY,
    Control,
    Placement,
    Section,
    enumerate_schema_paths,
    load_schema,
    registry_paths,
    uncovered_editable_paths,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED_SCHEMA = _REPO_ROOT / "src" / "darth_infra" / "darth-infra.schema.json"
_ROOT_SCHEMA = _REPO_ROOT / "darth-infra.schema.json"


@pytest.fixture
def schema() -> dict:
    return load_schema()


def test_packaged_and_root_schema_byte_for_byte_identical() -> None:
    assert _PACKAGED_SCHEMA.read_bytes() == _ROOT_SCHEMA.read_bytes()


def test_cli_version_floor_is_explicitly_read_only(schema: dict) -> None:
    prop = schema["properties"]["project"]["properties"]["cli_version_floor"]
    assert prop.get("readOnly") is True


def test_cli_version_floor_is_the_only_read_only_field(schema: dict) -> None:
    fields = enumerate_schema_paths(schema)
    assert fields.read_only == {"project.cli_version_floor"}


def test_registry_covers_every_editable_schema_field(schema: dict) -> None:
    editable = set(enumerate_schema_paths(schema).editable)
    covered = registry_paths()

    missing = editable - covered
    extra = covered - editable
    assert not missing, f"editable schema paths without a registry entry: {sorted(missing)}"
    assert not extra, f"registry paths not present in the schema: {sorted(extra)}"


def test_read_only_fields_are_absent_from_editable_coverage(schema: dict) -> None:
    fields = enumerate_schema_paths(schema)
    assert "project.cli_version_floor" not in fields.editable
    assert "project.cli_version_floor" not in registry_paths()


def test_registry_entries_have_required_metadata() -> None:
    for entry in FIELD_REGISTRY:
        assert isinstance(entry.section, Section)
        assert isinstance(entry.placement, Placement)
        assert isinstance(entry.control, Control)
        assert entry.help.strip(), f"empty help for {entry.path}"


def test_registry_paths_are_unique() -> None:
    paths = [entry.path for entry in FIELD_REGISTRY]
    assert len(paths) == len(set(paths))


def test_representative_container_and_leaf_shapes_are_enumerated(schema: dict) -> None:
    editable = set(enumerate_schema_paths(schema).editable)
    # array of objects nested inside an array of objects
    assert "services[].ebs_volumes[].name" in editable
    # map of scalars inside an array of objects
    assert "services[].environment_variables.*" in editable
    # map of objects whose values contain a nested scalar map
    assert "environments.*.tags.*" in editable
    assert "environments.*.ec2_instance_type_override.*" in editable
    # nullable scalar leaf
    assert "alb.path_rules[].priority" in editable
    # scalar list container
    assert "project.private_subnet_ids" in editable


def test_coverage_fails_when_schema_gains_an_uncovered_editable_field(
    schema: dict,
) -> None:
    mutated = copy.deepcopy(schema)
    mutated["properties"]["project"]["properties"]["new_setting"] = {
        "type": "string",
        "description": "A brand new user-authored field.",
    }
    uncovered = uncovered_editable_paths(mutated)
    assert "project.new_setting" in uncovered


def test_coverage_permits_a_newly_added_explicit_read_only_field(
    schema: dict,
) -> None:
    mutated = copy.deepcopy(schema)
    mutated["properties"]["project"]["properties"]["managed_marker"] = {
        "type": "string",
        "description": "CLI-maintained metadata.",
        "readOnly": True,
    }
    fields = enumerate_schema_paths(mutated)
    assert "project.managed_marker" in fields.read_only
    assert "project.managed_marker" not in fields.editable
    assert not uncovered_editable_paths(mutated)


def test_runtime_only_active_preview_absent_from_schema_and_registry(
    schema: dict,
) -> None:
    schema_text = json.dumps(schema)
    assert "active_preview" not in schema_text
    assert not any("active_preview" in path for path in registry_paths())


def test_json_schema_meta_keys_are_not_editable_fields(schema: dict) -> None:
    editable = set(enumerate_schema_paths(schema).editable)
    assert "$schema" not in editable
    assert not any(path.startswith("$") for path in editable)
