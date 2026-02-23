"""``darth-infra deploy`` — deploy an environment."""

from __future__ import annotations

import click

from .cfn import (
    deploy_changeset,
    ensure_artifact_bucket,
    package_template,
    resolve_lookup_data,
)
from .helpers import console, require_config, require_prod_deployed
from ..scaffold.generator import generate_project


@click.command()
@click.option(
    "--env",
    "env_name",
    required=True,
    help="Environment to deploy (e.g. prod, dev, feature-xyz).",
)
@click.option(
    "--no-execute",
    is_flag=True,
    default=False,
    help="Create a CloudFormation change set but do not execute it.",
)
@click.option(
    "--changeset-name",
    default=None,
    help="Optional explicit change set name.",
)
def deploy(env_name: str, no_execute: bool, changeset_name: str | None) -> None:
    """Deploy the CloudFormation stack for a given environment."""
    config, project_dir = require_config()

    if env_name not in config.environments:
        console.print(
            f"[red]Environment '{env_name}' not found in darth-infra.toml. "
            f"Available: {', '.join(config.environments)}[/red]"
        )
        raise SystemExit(1)

    require_prod_deployed(config, env_name)

    console.print(
        f"[bold]Deploying [cyan]{config.project_name}[/cyan] "
        f"environment [cyan]{env_name}[/cyan]...[/bold]"
    )

    try:
        console.print("[dim]Refreshing CloudFormation templates from darth-infra.toml...[/dim]")
        generate_project(config, project_dir)

        lookups = resolve_lookup_data(config, env_name)
        bucket = ensure_artifact_bucket(config)
        packaged_template = package_template(project_dir, config, env_name, bucket)
        rc = deploy_changeset(
            config,
            env_name,
            packaged_template,
            lookups,
            no_execute=no_execute,
            changeset_name=changeset_name,
        )
    except Exception as exc:
        console.print(f"[red]Deploy setup failed: {exc}[/red]")
        raise SystemExit(1)

    if rc == 0:
        if no_execute:
            console.print(
                f"[green]✓ Change set prepared successfully for {env_name}[/green]"
            )
        else:
            console.print(f"[green]✓ Deployed {env_name} successfully[/green]")
    else:
        console.print(f"[red]Deploy failed with exit code {rc}[/red]")
        raise SystemExit(rc)
