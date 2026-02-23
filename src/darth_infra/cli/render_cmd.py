"""``darth-infra render`` — regenerate CloudFormation templates from config."""

from __future__ import annotations

from pathlib import Path

import click

from ..scaffold.generator import generate_project
from .helpers import console, require_config


@click.command("render")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory to render templates into. Defaults to the config directory.",
)
def render_cmd(output_dir: Path | None) -> None:
    """Regenerate CloudFormation templates from ``darth-infra.toml``."""
    config, project_dir = require_config()

    target_dir = output_dir or project_dir
    result = generate_project(config, target_dir)

    console.print(f"[green]✓ Templates rendered at {result / 'templates'}[/green]")
