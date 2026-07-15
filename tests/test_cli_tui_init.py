"""CLI cutover contract for ``darth-infra tui`` and ``darth-infra init``.

After the atomic cutover the CLI exposes two distinct commands: ``tui`` is the
ongoing document-preserving editor for an existing project, and ``init`` is the
first-run project-creation command. These tests exercise the command wiring
without launching Textual (the editor's own ``run`` is stubbed); full-app
behavior is covered by the Textual Pilot acceptance suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from darth_infra.cli.main import cli
from darth_infra.config.loader import CONFIG_FILENAME, dump_config
from darth_infra.config.models import ProjectConfig, ServiceConfig
from darth_infra.tui.editor import ConfigEditorApp

EXISTING = """\
[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
"""


@pytest.fixture
def captured_apps(monkeypatch: pytest.MonkeyPatch) -> list[ConfigEditorApp]:
    """Stub the editor's ``run`` so commands construct but never launch it."""
    apps: list[ConfigEditorApp] = []

    def fake_run(self: ConfigEditorApp) -> None:
        apps.append(self)

    monkeypatch.setattr(ConfigEditorApp, "run", fake_run)
    return apps


def _write_existing(tmp_path: Path) -> Path:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(EXISTING)
    return path


def test_help_lists_distinct_tui_and_init_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "tui" in result.output
    assert "init" in result.output

    tui_help = CliRunner().invoke(cli, ["tui", "--help"])
    assert tui_help.exit_code == 0
    assert "existing" in tui_help.output.lower()

    init_help = CliRunner().invoke(cli, ["init", "--help"])
    assert init_help.exit_code == 0
    assert "new" in init_help.output.lower()


def test_tui_opens_existing_config_in_existing_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured_apps: list
) -> None:
    path = _write_existing(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["tui"])

    assert result.exit_code == 0, result.output
    assert len(captured_apps) == 1
    app = captured_apps[0]
    assert app._mode == "existing"
    assert app._document.path == path


def test_tui_errors_actionably_when_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured_apps: list
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["tui"])

    assert result.exit_code != 0
    assert "darth-infra init" in result.output
    # It never fell through to launching the editor.
    assert captured_apps == []


def test_interactive_init_opens_creation_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured_apps: list
) -> None:
    out = tmp_path / "proj"
    out.mkdir()

    result = CliRunner().invoke(cli, ["init", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert len(captured_apps) == 1
    app = captured_apps[0]
    assert app._mode == "create"
    assert app._output_dir == out
    # Creation defers to Review: no files were written by merely constructing it.
    assert not (out / CONFIG_FILENAME).exists()


def test_non_interactive_init_scaffolds_without_launching_textual(
    tmp_path: Path, captured_apps: list
) -> None:
    config = ProjectConfig(project_name="demo", services=[ServiceConfig(name="web")])
    config_path = tmp_path / "seed.toml"
    config_path.write_text(dump_config(config))
    out = tmp_path / "generated"

    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--non-interactive",
            "--config",
            str(config_path),
            "--output",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    # The editor was never constructed for a non-interactive scaffold.
    assert captured_apps == []
    assert (out / CONFIG_FILENAME).is_file()
    assert (out / "templates" / "generated" / "root.yaml").is_file()


def test_non_interactive_init_requires_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["init", "--non-interactive"])

    assert result.exit_code != 0
    assert "--config is required" in result.output
