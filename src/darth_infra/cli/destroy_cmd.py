"""``darth-infra destroy`` — tear down an environment's stack."""

from __future__ import annotations

import boto3
import click

from .cfn import (
    cleanup_preview_service_discovery_instances,
    delete_stack,
    delete_preview_database_instance,
    delete_tagged_preview_snapshots,
    empty_managed_buckets,
    empty_managed_repositories,
)
from .helpers import console, is_active_preview, require_config, resolve_environment_config
from .version_floor import bump_cli_version_floor


@click.command()
@click.option("--env", "env_name", required=True, help="Environment to destroy.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.option(
    "--preview-from",
    default=None,
    help="Base environment to use for a dynamic preview environment.",
)
def destroy(env_name: str, force: bool, preview_from: str | None) -> None:
    """Destroy the CloudFormation stack for a given environment."""
    loaded_config, project_dir = require_config()
    config = resolve_environment_config(loaded_config, env_name, preview_from)

    if env_name == "prod":
        # Verify no non-prod envs still exist
        cf = boto3.client("cloudformation", region_name=config.aws_region)
        for other_env in config.environments:
            if other_env == "prod":
                continue
            try:
                cf.describe_stacks(StackName=f"{config.project_name}-ecs-{other_env}")
                console.print(
                    f"[red]Cannot destroy prod while '{other_env}' "
                    f"environment still exists. Destroy it first.[/red]"
                )
                raise SystemExit(1)
            except cf.exceptions.ClientError:
                pass  # Stack doesn't exist, fine

    if not force:
        click.confirm(
            f"Destroy environment '{env_name}' for '{config.project_name}'?",
            abort=True,
        )

    console.print(
        f"[bold]Destroying [cyan]{config.project_name}[/cyan] "
        f"environment [cyan]{env_name}[/cyan]...[/bold]"
    )

    if is_active_preview(config, env_name):
        empty_rc = empty_managed_buckets(config, env_name)
        if empty_rc != 0:
            raise SystemExit(empty_rc)
        ecr_rc = empty_managed_repositories(config, env_name)
        if ecr_rc != 0:
            raise SystemExit(ecr_rc)
        cloud_map_rc = cleanup_preview_service_discovery_instances(config, env_name)
        if cloud_map_rc != 0:
            raise SystemExit(cloud_map_rc)
        db_rc = delete_preview_database_instance(config, env_name)
        if db_rc != 0:
            raise SystemExit(db_rc)

    rc = delete_stack(config, env_name)

    if rc == 0 and is_active_preview(config, env_name):
        snapshot_rc = delete_tagged_preview_snapshots(config, env_name)
        if snapshot_rc != 0:
            raise SystemExit(snapshot_rc)

    if rc == 0:
        bump_cli_version_floor(project_dir)
        console.print(f"[green]✓ Destroyed {env_name}[/green]")
    else:
        console.print(f"[red]Destroy failed with exit code {rc}[/red]")
        raise SystemExit(rc)
