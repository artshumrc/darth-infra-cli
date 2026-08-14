"""``darth-infra install-skill`` installs the config-authoring skill for agents."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from darth_infra.cli.install_skill_cmd import (
    SKILL_NAME,
    install_skill_cmd,
    install_skill_for_new_project,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGED_SKILL = _REPO_ROOT / "src" / "darth_infra" / "skill" / "SKILL.md"

_CLAUDE = Path(".claude") / "skills" / SKILL_NAME
_AGENTS = Path(".agents") / "skills" / SKILL_NAME


def _invoke(tmp_path: Path, *args: str):
    result = CliRunner().invoke(
        install_skill_cmd, ["--output", str(tmp_path), *args]
    )
    assert result.exit_code == 0, result.output
    return result


def test_installs_into_both_agent_directories(tmp_path: Path) -> None:
    _invoke(tmp_path)

    for target in (_CLAUDE, _AGENTS):
        assert (tmp_path / target / "SKILL.md").is_file()
        assert (tmp_path / target / "reference" / "darth-infra.schema.json").is_file()


def test_target_selects_a_single_directory(tmp_path: Path) -> None:
    _invoke(tmp_path, "--target", "claude")

    assert (tmp_path / _CLAUDE / "SKILL.md").is_file()
    assert not (tmp_path / ".agents").exists()


def test_installed_schema_matches_the_packaged_schema(tmp_path: Path) -> None:
    """The bundled reference is the field surface the agent authors against."""
    _invoke(tmp_path)

    installed = json.loads(
        (tmp_path / _CLAUDE / "reference" / "darth-infra.schema.json").read_text()
    )
    packaged = json.loads(
        (_REPO_ROOT / "darth-infra.schema.json").read_text()
    )

    assert installed == packaged


def test_reinstalling_refreshes_an_edited_skill(tmp_path: Path) -> None:
    _invoke(tmp_path)
    (tmp_path / _CLAUDE / "SKILL.md").write_text("stale", encoding="utf-8")

    result = _invoke(tmp_path)

    assert "Updated" in result.output
    assert (tmp_path / _CLAUDE / "SKILL.md").read_text() == _PACKAGED_SKILL.read_text()


def test_first_install_reports_installed(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--target", "claude")

    assert "Installed" in result.output


def test_skill_has_the_frontmatter_agents_discover_it_by() -> None:
    text = _PACKAGED_SKILL.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "---"
    closing = lines.index("---", 1)
    frontmatter = "\n".join(lines[1:closing])
    assert f"name: {SKILL_NAME}" in frontmatter
    assert "description:" in frontmatter


def test_init_installs_the_skill_into_a_created_project(tmp_path: Path) -> None:
    (tmp_path / "darth-infra.toml").write_text("[project]\n", encoding="utf-8")

    install_skill_for_new_project(tmp_path, skip=False)

    assert (tmp_path / _CLAUDE / "SKILL.md").is_file()
    assert (tmp_path / _AGENTS / "SKILL.md").is_file()


def test_cancelled_creation_leaves_nothing_behind(tmp_path: Path) -> None:
    """The guided editor writes no config until Review is confirmed."""
    install_skill_for_new_project(tmp_path, skip=False)

    assert list(tmp_path.iterdir()) == []


def test_no_skill_flag_suppresses_the_install(tmp_path: Path) -> None:
    (tmp_path / "darth-infra.toml").write_text("[project]\n", encoding="utf-8")

    install_skill_for_new_project(tmp_path, skip=True)

    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".agents").exists()


def test_skill_documents_every_top_level_config_table() -> None:
    """A table absent from the skill is one an agent will not know exists."""
    schema = json.loads((_REPO_ROOT / "darth-infra.schema.json").read_text())
    text = _PACKAGED_SKILL.read_text(encoding="utf-8")

    missing = [
        name
        for name in schema["properties"]
        if not name.startswith("$") and name not in text
    ]

    assert not missing, f"config tables absent from the skill: {missing}"
