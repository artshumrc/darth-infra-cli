"""``darth-infra deploy`` — deploy an environment."""

from __future__ import annotations

import click

from .helpers import console, require_config, require_prod_deployed, run_cdk


@click.command()
@click.option(
    "--env",
    "env_name",
    required=True,
    help="Environment to deploy (e.g. prod, dev, feature-xyz).",
)
@click.option(
    "--require-approval",
    type=click.Choice(["never", "any-change", "broadening"]),
    default="broadening",
    help="CDK approval level for security-sensitive changes.",
)
def deploy(env_name: str, require_approval: str) -> None:
    """Deploy the CDK stack for a given environment."""
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

    stack_name = f"{config.project_name}-ecs-{env_name}"
    rc = run_cdk(
        [
            "deploy",
            stack_name,
            "--require-approval",
            require_approval,
            "-c",
            f"target_env={env_name}",
        ],
        project_dir,
    )

    if rc == 0:
        console.print(f"[green]✓ Deployed {env_name} successfully[/green]")
    else:
        console.print(f"[red]Deploy failed with exit code {rc}[/red]")
        raise SystemExit(rc)
