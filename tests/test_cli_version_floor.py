from __future__ import annotations

import click
import pytest
from packaging.version import Version

from darth_infra.cli import version_floor
from darth_infra.cli.helpers import require_config
from darth_infra.config.loader import CONFIG_FILENAME, dump_config, load_config
from darth_infra.config.models import ProjectConfig, ServiceConfig


def _config(version: str | None = None) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        cli_version_floor=version,
    )


def test_config_roundtrip_preserves_cli_version_floor(tmp_path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(dump_config(_config("0.7.2")))

    loaded = load_config(path)

    assert loaded.cli_version_floor == "0.7.2"
    assert 'cli_version_floor = "0.7.2"' in dump_config(loaded)


def test_missing_cli_version_floor_is_allowed() -> None:
    config = _config()

    assert config.cli_version_floor is None
    assert "cli_version_floor" not in dump_config(config)


@pytest.mark.parametrize("floor", [None, "1.2.3", "1.2.2"])
def test_enforce_cli_version_floor_allows_missing_equal_and_older(
    monkeypatch: pytest.MonkeyPatch, floor: str | None
) -> None:
    monkeypatch.setattr(version_floor, "get_current_cli_version", lambda: Version("1.2.3"))

    version_floor.enforce_cli_version_floor(_config(floor))


def test_enforce_cli_version_floor_blocks_newer_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_floor, "get_current_cli_version", lambda: Version("1.2.3"))

    with pytest.raises(click.ClickException, match="requires darth-infra CLI >= 1.2.4"):
        version_floor.enforce_cli_version_floor(_config("1.2.4"))


def test_invalid_cli_version_floor_fails_validation() -> None:
    with pytest.raises(ValueError, match="cli_version_floor is not a valid version"):
        _config("not-a-version")


@pytest.mark.parametrize("floor", [None, "1.2.2"])
def test_bump_cli_version_floor_writes_missing_or_older(
    monkeypatch: pytest.MonkeyPatch, tmp_path, floor: str | None
) -> None:
    monkeypatch.setattr(version_floor, "get_current_cli_version", lambda: Version("1.2.3"))
    monkeypatch.setattr(version_floor, "get_current_cli_version_string", lambda: "1.2.3")
    path = tmp_path / CONFIG_FILENAME
    path.write_text(dump_config(_config(floor)))

    version_floor.bump_cli_version_floor(tmp_path)

    assert load_config(path).cli_version_floor == "1.2.3"


@pytest.mark.parametrize("floor", ["1.2.3", "1.2.4"])
def test_bump_cli_version_floor_does_not_rewrite_equal_or_newer(
    monkeypatch: pytest.MonkeyPatch, tmp_path, floor: str
) -> None:
    monkeypatch.setattr(version_floor, "get_current_cli_version", lambda: Version("1.2.3"))
    monkeypatch.setattr(version_floor, "get_current_cli_version_string", lambda: "1.2.3")
    path = tmp_path / CONFIG_FILENAME
    original = dump_config(_config(floor))
    path.write_text(original)

    version_floor.bump_cli_version_floor(tmp_path)

    assert path.read_text() == original
    assert load_config(path).cli_version_floor == floor


def test_require_config_enforces_cli_version_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(version_floor, "get_current_cli_version", lambda: Version("1.2.3"))
    (tmp_path / CONFIG_FILENAME).write_text(dump_config(_config("1.2.4")))

    with pytest.raises(click.ClickException):
        require_config()
