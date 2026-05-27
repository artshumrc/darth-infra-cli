"""``darth-infra tui`` — visual editor for darth-infra.toml using Textual."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from ..config.loader import find_config, load_config
from ..tui.wizard_export import project_config_to_wizard_state
from .version_floor import apply_current_cli_version_floor, enforce_cli_version_floor

console = Console()


@click.command("tui")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for the CloudFormation project. Defaults to the current directory.",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    default=False,
    help="Skip the TUI and use a config file instead.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to an existing darth-infra.toml (for non-interactive mode).",
)
def init_cmd(
    output_dir: Path | None,
    non_interactive: bool,
    config_path: Path | None,
) -> None:
    """Launch the TUI to edit/validate config and scaffold CloudFormation output."""
    from ..scaffold.generator import generate_project

    if non_interactive:
        if config_path is None:
            raise click.UsageError("--config is required when using --non-interactive")
        config = load_config(config_path)
        enforce_cli_version_floor(config)
        apply_current_cli_version_floor(config)
        out = output_dir or Path.cwd()
        result = generate_project(config, out)
        console.print(f"[green]Project scaffolded at {result}[/green]")
        return

    # Interactive TUI
    from ..tui.app import DarthEcsInitApp

    seed_state = None
    try:
        existing_path = find_config(Path.cwd())
        existing_config = load_config(existing_path)
        enforce_cli_version_floor(existing_config)
        seed_state = project_config_to_wizard_state(existing_config)
        console.print(f"[dim]Loaded seed values from {existing_path}[/dim]")
    except FileNotFoundError:
        pass

    app = DarthEcsInitApp(seed_state=seed_state)
    app.run()

    if app.result_config is None:
        console.print("[yellow]Setup cancelled.[/yellow]")
        return

    config = app.result_config
    apply_current_cli_version_floor(config)
    out = output_dir or Path.cwd()
    result = generate_project(config, out)
    console.print(f"\n[green]✓ Project scaffolded at {result}[/green]")
    console.print(
        f"\n[dim]Next steps:[/dim]\n  cd {result.name}\n  darth-infra deploy --env prod\n"
    )
