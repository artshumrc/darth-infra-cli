"""``darth-infra init`` — interactive project setup using Textual TUI."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from ..tui.wizard_export import load_wizard_export

console = Console()


@click.command("init")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for the CloudFormation project. Defaults to ./<project-name>-infra.",
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
@click.option(
    "--seed-out",
    "wizard_export_path",
    type=click.Path(path_type=Path),
    default=Path.cwd() / "wizard-export.json",
    show_default=True,
    help="Path to write wizard draft/export JSON (interactive mode).",
)
@click.option(
    "--seed",
    "seed_wizard_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Load wizard seed data from a previous wizard-export.json.",
)
def init_cmd(
    output_dir: Path | None,
    non_interactive: bool,
    config_path: Path | None,
    wizard_export_path: Path,
    seed_wizard_path: Path | None,
) -> None:
    """Interactively scaffold a new darth-infra CloudFormation project."""
    from ..config.loader import load_config
    from ..scaffold.generator import generate_project

    if non_interactive:
        if config_path is None:
            raise click.UsageError("--config is required when using --non-interactive")
        config = load_config(config_path)
        out = output_dir or Path.cwd() / f"{config.project_name}-infra"
        result = generate_project(config, out)
        console.print(f"[green]Project scaffolded at {result}[/green]")
        return

    # Interactive TUI
    from ..tui.app import DarthEcsInitApp

    seed_state = None
    if seed_wizard_path is not None:
        export = load_wizard_export(seed_wizard_path)
        if export is None:
            console.print(
                f"[yellow]Could not parse wizard seed: {seed_wizard_path}. Starting fresh.[/yellow]"
            )
        else:
            seed_state = export.state
            console.print(f"[dim]Loaded wizard seed from {seed_wizard_path}[/dim]")

    app = DarthEcsInitApp(
        seed_state=seed_state,
        wizard_export_path=str(wizard_export_path),
    )
    app.run()

    if app.result_config is None:
        console.print("[yellow]Setup cancelled.[/yellow]")
        console.print(
            f"[dim]Wizard draft saved to {wizard_export_path} "
            f"(resume with --seed {wizard_export_path})[/dim]"
        )
        return

    config = app.result_config
    out = output_dir or Path.cwd() / f"{config.project_name}-infra"
    result = generate_project(config, out)
    console.print(f"\n[green]✓ Project scaffolded at {result}[/green]")
    console.print(
        f"[dim]Wizard export saved to {wizard_export_path} "
        f"(can be reused with --seed).[/dim]"
    )
    console.print(
        f"\n[dim]Next steps:[/dim]\n  cd {result.name}\n  darth-infra deploy --env prod\n"
    )
