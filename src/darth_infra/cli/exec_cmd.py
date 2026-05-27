"""``darth-infra exec`` — interactive shell into an ECS container."""

from __future__ import annotations

import subprocess

import boto3
import click

from .helpers import console, get_cluster_name, get_service_name, require_config
from .version_floor import bump_cli_version_floor


@click.command("exec")
@click.argument("service")
@click.option("--env", "env_name", required=True, help="Environment name.")
@click.option(
    "--command",
    "shell_cmd",
    default="/bin/sh",
    help="Command to run in the container.",
)
def exec_cmd(service: str, env_name: str, shell_cmd: str) -> None:
    """Open an interactive shell in a running ECS container."""
    config, project_dir = require_config()

    svc = next((s for s in config.services if s.name == service), None)
    if svc is None:
        console.print(
            f"[red]Service '{service}' not found. "
            f"Available: {', '.join(s.name for s in config.services)}[/red]"
        )
        raise SystemExit(1)

    cluster = get_cluster_name(config.project_name, env_name)
    service_name = get_service_name(config.project_name, env_name, service)

    console.print(
        f"[bold]Finding running task for [cyan]{service_name}[/cyan]...[/bold]"
    )

    ecs = boto3.client("ecs", region_name=config.aws_region)

    # Find a running task
    tasks = ecs.list_tasks(
        cluster=cluster,
        serviceName=service_name,
        desiredStatus="RUNNING",
    )
    task_arns = tasks.get("taskArns", [])
    if not task_arns:
        console.print(
            f"[red]No running tasks found for {service_name} in cluster {cluster}[/red]"
        )
        raise SystemExit(1)

    task_arn = task_arns[0]
    task_id = task_arn.split("/")[-1]
    console.print(f"[dim]Task: {task_id}[/dim]")

    # Use AWS CLI for interactive session (boto3 doesn't support interactive)
    cmd = [
        "aws",
        "ecs",
        "execute-command",
        "--cluster",
        cluster,
        "--task",
        task_arn,
        "--container",
        service,
        "--interactive",
        "--command",
        shell_cmd,
        "--region",
        config.aws_region,
    ]

    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(cmd)
    except KeyboardInterrupt:
        return
    if result.returncode == 0:
        bump_cli_version_floor(project_dir)
