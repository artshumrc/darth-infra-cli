"""``darth-infra status`` — show environment status."""

from __future__ import annotations

import boto3
import click
from rich.table import Table

from .helpers import (
    console,
    get_cluster_name,
    get_service_name,
    require_config,
    resolve_environment_config,
)


@click.command()
@click.option("--env", "env_name", required=True, help="Environment name.")
@click.option(
    "--preview-from",
    default=None,
    help="Base environment to use for a dynamic preview environment.",
)
def status(env_name: str, preview_from: str | None) -> None:
    """Show the status of services in an environment."""
    loaded_config, _ = require_config()
    config = resolve_environment_config(loaded_config, env_name, preview_from)

    ecs = boto3.client("ecs", region_name=config.aws_region)
    cluster = get_cluster_name(config.project_name, env_name)

    table = Table(title=f"{config.project_name} — {env_name}")
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Running", justify="right")
    table.add_column("Desired", justify="right")
    table.add_column("Pending", justify="right")

    for svc in config.services:
        service_name = get_service_name(config.project_name, env_name, svc.name)
        try:
            resp = ecs.describe_services(cluster=cluster, services=[service_name])
            if resp["services"]:
                s = resp["services"][0]
                status_str = s.get("status", "UNKNOWN")
                running = str(s.get("runningCount", 0))
                desired = str(s.get("desiredCount", 0))
                pending = str(s.get("pendingCount", 0))

                color = "green" if status_str == "ACTIVE" else "yellow"
                table.add_row(
                    svc.name,
                    f"[{color}]{status_str}[/{color}]",
                    running,
                    desired,
                    pending,
                )
            else:
                table.add_row(svc.name, "[red]NOT FOUND[/red]", "-", "-", "-")
        except Exception:
            table.add_row(svc.name, "[red]ERROR[/red]", "-", "-", "-")

    console.print(table)

    # RDS status
    if config.rds:
        console.print()
        rds_client = boto3.client("rds", region_name=config.aws_region)
        db_id = f"{config.project_name}-{env_name}-db"
        try:
            resp = rds_client.describe_db_instances(DBInstanceIdentifier=db_id)
            if resp["DBInstances"]:
                db = resp["DBInstances"][0]
                db_status = db.get("DBInstanceStatus", "unknown")
                endpoint = db.get("Endpoint", {}).get("Address", "N/A")
                color = "green" if db_status == "available" else "yellow"
                console.print(
                    f"[bold]RDS:[/bold] [{color}]{db_status}[/{color}] — {endpoint}"
                )
        except Exception:
            console.print("[bold]RDS:[/bold] [red]not found[/red]")
