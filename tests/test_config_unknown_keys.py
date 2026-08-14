"""Unrecognized configuration keys are rejected instead of silently ignored.

The parsers read the keys they know and drop the rest, so without this check a
misspelled key deploys its default without comment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darth_infra.config.loader import load_config
from darth_infra.config.schema import load_schema, unknown_keys

_VALID = """\
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "main-vpc"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_config_reports_nothing(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, _VALID)).project_name == "demo"


def test_a_misspelled_service_key_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID + 'memory_mb = 2048\n')

    with pytest.raises(ValueError, match=r"services\[0\].memory_mb"):
        load_config(path)


def test_the_error_suggests_the_intended_key(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID + 'memory_mb = 2048\n')

    with pytest.raises(ValueError, match="did you mean 'memory_mib'"):
        load_config(path)


def test_a_misspelled_table_key_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _VALID + '\n[rds]\ndatabase_name = "app"\ninstance_typ = "db.t4g.large"\n'
    )

    with pytest.raises(ValueError, match=r"rds.instance_typ.*instance_type"):
        load_config(path)


def test_every_unknown_key_is_reported_at_once(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _VALID + 'made_up = 1\n\n[alb]\nmode = "shared"\nnonsense = true\n',
    )

    with pytest.raises(ValueError) as excinfo:
        load_config(path)

    assert "services[0].made_up" in str(excinfo.value)
    assert "alb.nonsense" in str(excinfo.value)


def test_free_form_tables_accept_any_key() -> None:
    raw = {
        "project": {"name": "demo", "tags": {"anything-at-all": "yes"}},
        "services": [{"name": "web", "environment_variables": {"WHATEVER": "1"}}],
        "environments": {"staging": {"tags": {"cost-center": "sandbox"}}},
    }

    assert unknown_keys(raw) == []


def test_unknown_keys_inside_a_free_form_table_are_still_caught() -> None:
    raw = {"environments": {"staging": {"instance_type_overide": "db.t4g.small"}}}

    found = unknown_keys(raw)

    assert [key.path for key in found] == ["environments.staging.instance_type_overide"]
    assert found[0].suggestion == "instance_type_override"


def test_nested_collections_are_walked() -> None:
    raw = {
        "s3_buckets": [
            {"name": "media", "connections": [{"service": "web", "env_ky": "X"}]}
        ]
    }

    assert [key.path for key in unknown_keys(raw)] == [
        "s3_buckets[0].connections[0].env_ky"
    ]


def test_the_cli_reports_the_error_without_a_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    from click.testing import CliRunner

    from darth_infra.cli.main import cli

    _write(tmp_path, _VALID + "memory_mb = 2048\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["render"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "did you mean 'memory_mib'" in result.output
    assert "Traceback" not in result.output


def test_every_schema_object_is_closed() -> None:
    """An object missing additionalProperties:false silently opts out of this check."""
    schema = load_schema()
    open_objects: list[str] = []

    def walk(node: dict, path: str) -> None:
        if "properties" in node and node.get("additionalProperties") is not False:
            open_objects.append(path or "<root>")
        for name, child in node.get("properties", {}).items():
            walk(child, f"{path}.{name}" if path else name)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, f"{path}[]")
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            walk(additional, f"{path}.<*>")

    walk(schema, "")

    assert not open_objects, f"schema objects open to unknown keys: {open_objects}"
