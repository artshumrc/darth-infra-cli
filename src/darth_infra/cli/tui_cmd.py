"""``darth-infra tui`` — the Guided editor for an existing project.

This is the ongoing editing entry point. It opens an existing
``darth-infra.toml`` through :class:`~darth_infra.config.document.ProjectDocument`
and the Guided editor, performing document-preserving saves. It never
scaffolds, renders, deploys, or mutates live infrastructure; first-run project
creation is the job of ``darth-infra init`` (see
:mod:`darth_infra.cli.init_cmd`).
"""

from __future__ import annotations

from pathlib import Path

import click

from ..config.loader import find_config, load_config
from .version_floor import enforce_cli_version_floor


@click.command("tui")
def tui_cmd() -> None:
    """Edit an existing darth-infra.toml with the Guided configuration editor."""
    from ..config.document import ProjectDocument
    from ..tui.editor import ConfigEditorApp

    try:
        config_path = find_config(Path.cwd())
    except FileNotFoundError as exc:
        raise click.ClickException(
            "No darth-infra.toml found in this directory or any parent. "
            "Run `darth-infra init` to create a new project."
        ) from exc

    # Version-floor enforcement retains current semantics: an existing project
    # authored by a newer CLI is rejected before the editor opens.
    enforce_cli_version_floor(load_config(config_path))

    app = ConfigEditorApp(document=ProjectDocument.load(config_path), mode="existing")
    app.run()
