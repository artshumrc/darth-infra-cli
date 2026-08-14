"""``darth-infra install-skill`` — install the config-authoring agent skill.

The skill teaches an agent to write ``darth-infra.toml`` directly, covering the
AWS lookups and cross-field rules the schema alone cannot express. It ships the
packaged JSON schema alongside itself as the authoritative field reference, so an
installed skill always matches the CLI version that installed it.

Copies are written per target rather than symlinked: re-running this command is
how a skill is updated, so the copies never need to stay in sync by themselves.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click
from rich.console import Console

console = Console()

SKILL_NAME = "darth-infra-toml"

_SKILL_SRC = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
_SCHEMA_SRC = Path(__file__).resolve().parent.parent / "darth-infra.schema.json"

# Where each agent runtime discovers project-local skills.
_TARGET_DIRS = {
    "claude": Path(".claude") / "skills",
    "agents": Path(".agents") / "skills",
}


def _install_one(skills_root: Path) -> tuple[Path, bool]:
    """Write the skill into *skills_root*. Returns the path and whether it existed."""
    skill_dir = skills_root / SKILL_NAME
    existed = (skill_dir / "SKILL.md").exists()

    reference_dir = skill_dir / "reference"
    reference_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_SKILL_SRC, skill_dir / "SKILL.md")
    shutil.copy2(_SCHEMA_SRC, reference_dir / _SCHEMA_SRC.name)

    return skill_dir, existed


def install_skill_for_new_project(project_dir: Path, *, skip: bool) -> None:
    """Install the skill into a project ``init`` has just created.

    No-ops when the config file is absent, so cancelling creation in the guided
    editor leaves nothing behind.
    """
    from ..config.loader import CONFIG_FILENAME

    if skip or not (project_dir / CONFIG_FILENAME).exists():
        return

    for relative in _TARGET_DIRS.values():
        _install_one(project_dir / relative)

    console.print(
        "[green]✓ Installed the darth-infra.toml authoring skill for coding agents"
        "[/green] [dim](skip with --no-skill)[/dim]"
    )


@click.command("install-skill")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project directory to install into. Defaults to the current directory.",
)
@click.option(
    "--target",
    type=click.Choice(["both", "claude", "agents"]),
    default="both",
    show_default=True,
    help="Which agent skill directories to install into.",
)
def install_skill_cmd(output_dir: Path | None, target: str) -> None:
    """Install the darth-infra.toml authoring skill for coding agents."""
    if not _SKILL_SRC.exists():
        raise click.ClickException(
            f"Packaged skill is missing at {_SKILL_SRC}; reinstall darth-infra."
        )

    root = (output_dir or Path.cwd()).resolve()
    targets = list(_TARGET_DIRS) if target == "both" else [target]

    for name in targets:
        skill_dir, existed = _install_one(root / _TARGET_DIRS[name])
        verb = "Updated" if existed else "Installed"
        console.print(f"[green]✓ {verb} {name} skill at {skill_dir}[/green]")

    console.print(
        "\nAsk your agent to write or edit darth-infra.toml and it will pick this up. "
        "Re-run this command after upgrading darth-infra to refresh the schema."
    )
