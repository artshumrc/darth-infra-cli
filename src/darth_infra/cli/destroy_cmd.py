"""``darth-infra destroy`` — tear down an environment's stack."""

from __future__ import annotations

import boto3
import click

from .helpers import console, require_config, run_cdk


@click.command()
@click.option("--env", "env_name", required=True, help="Environment to destroy.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def destroy(env_name: str, force: bool) -> None:
    """Destroy the CDK stack for a given environment."""
    config, project_dir = require_config()

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

    stack_name = f"{config.project_name}-ecs-{env_name}"
    rc = run_cdk(
        ["destroy", stack_name, "--force", "-c", f"target_env={env_name}"],
        project_dir,
    )

    if rc == 0:
        console.print(f"[green]✓ Destroyed {env_name}[/green]")
    else:
        console.print(f"[red]Destroy failed with exit code {rc}[/red]")
        raise SystemExit(rc)
