"""``darth-infra push`` — tag and push Docker images to ECR."""

from __future__ import annotations

import subprocess

import boto3
import click

from .helpers import console, require_config


@click.command()
@click.option(
    "--env",
    "env_name",
    required=True,
    help="Target environment (used for image tagging).",
)
@click.option(
    "--service",
    "service_name",
    default=None,
    help="Push only a specific service. Pushes all if omitted.",
)
def push(env_name: str, service_name: str | None) -> None:
    """Tag and push Docker images to ECR."""
    config, project_dir = require_config()

    services = config.services
    if service_name:
        services = [s for s in services if s.name == service_name]
        if not services:
            console.print(f"[red]Service '{service_name}' not found.[/red]")
            raise SystemExit(1)

    # ECR login
    account = boto3.client("sts").get_caller_identity()["Account"]
    region = config.aws_region
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"

    console.print("[bold]Logging in to ECR...[/bold]")
    login_cmd = (
        f"aws ecr get-login-password --region {region} "
        f"| docker login --username AWS --password-stdin {registry}"
    )
    result = subprocess.run(login_cmd, shell=True)
    if result.returncode != 0:
        console.print("[red]ECR login failed[/red]")
        raise SystemExit(1)

    for svc in services:
        if svc.image:
            console.print(
                f"[dim]Skipping {svc.name} — uses external image: {svc.image}[/dim]"
            )
            continue

        local_tag = f"{config.project_name}-{svc.name}:latest"
        ecr_repo = f"{registry}/{config.project_name}/{svc.name}"
        remote_tag = f"{ecr_repo}:{env_name}-latest"

        console.print(f"[bold]Pushing {svc.name} → {remote_tag}[/bold]")

        subprocess.run(["docker", "tag", local_tag, remote_tag], check=True)
        result = subprocess.run(["docker", "push", remote_tag])
        if result.returncode != 0:
            console.print(f"[red]Push failed for {svc.name}[/red]")
            raise SystemExit(result.returncode)

        console.print(f"[green]✓ Pushed {remote_tag}[/green]")
