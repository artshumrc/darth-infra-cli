"""``darth-infra build`` — build Docker images for all services."""

from __future__ import annotations

import subprocess

import click

from .helpers import console, require_config


@click.command()
@click.option(
    "--service",
    "service_name",
    default=None,
    help="Build only a specific service. Builds all if omitted.",
)
def build(service_name: str | None) -> None:
    """Build Docker images for configured services."""
    config, project_dir = require_config()

    services = config.services
    if service_name:
        services = [s for s in services if s.name == service_name]
        if not services:
            console.print(
                f"[red]Service '{service_name}' not found. "
                f"Available: {', '.join(s.name for s in config.services)}[/red]"
            )
            raise SystemExit(1)

    for svc in services:
        if svc.image:
            console.print(
                f"[dim]Skipping {svc.name} — uses external image: {svc.image}[/dim]"
            )
            continue

        tag = f"{config.project_name}-{svc.name}:latest"
        console.print(f"[bold]Building {svc.name}...[/bold]")

        cmd = [
            "docker",
            "build",
            "-t",
            tag,
            "-f",
            svc.dockerfile,
            svc.build_context,
        ]
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd, cwd=str(project_dir.parent))
        if result.returncode != 0:
            console.print(
                f"[red]Build failed for {svc.name} (exit {result.returncode})[/red]"
            )
            raise SystemExit(result.returncode)

        console.print(f"[green]✓ Built {tag}[/green]")
