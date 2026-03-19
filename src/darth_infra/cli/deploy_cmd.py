"""``darth-infra deploy`` — deploy an environment."""

from __future__ import annotations

import copy

import boto3
import click
from botocore.exceptions import ClientError

from .cfn import (
    cancel_stack_update,
    deploy_changeset,
    ensure_artifact_bucket,
    package_template,
    resolve_lookup_data,
    run_seed_copy_tasks,
    validate_rendered_deploy_templates,
)
from .helpers import (
    console,
    get_cluster_name,
    get_service_name,
    require_config,
    require_prod_deployed,
)
from .image_ops import build_images, push_images, select_internal_services
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
@click.option(
    "--with-images",
    is_flag=True,
    default=False,
    help="Build and push service images before deploying infrastructure.",
)
@click.option(
    "--cancel",
    "cancel_update",
    is_flag=True,
    default=False,
    help="Cancel an in-progress CloudFormation stack update for this environment.",
)
def deploy(
    env_name: str,
    no_execute: bool,
    changeset_name: str | None,
    with_images: bool,
    cancel_update: bool,
) -> None:
    """Deploy the CloudFormation stack for a given environment."""
    config, project_dir = require_config()

    if env_name not in config.environments:
        console.print(
            f"[red]Environment '{env_name}' not found in darth-infra.toml. "
            f"Available: {', '.join(config.environments)}[/red]"
        )
        raise SystemExit(1)

    if cancel_update and (no_execute or with_images or changeset_name is not None):
        console.print(
            "[red]--cancel cannot be combined with --no-execute, --with-images, or --changeset-name.[/red]"
        )
        raise SystemExit(1)

    if cancel_update:
        console.print(
            f"[bold]Cancelling in-progress deploy for [cyan]{config.project_name}[/cyan] "
            f"environment [cyan]{env_name}[/cyan]...[/bold]"
        )
        rc = cancel_stack_update(config, env_name)
        if rc == 0:
            console.print(f"[green]✓ Cancelled deploy for {env_name}[/green]")
            return

        console.print(f"[red]Cancel deploy failed with exit code {rc}[/red]")
        raise SystemExit(rc)

    require_prod_deployed(config, env_name)

    if with_images and no_execute:
        console.print("[red]--with-images cannot be combined with --no-execute.[/red]")
        raise SystemExit(1)

    console.print(
        f"[bold]Deploying [cyan]{config.project_name}[/cyan] "
        f"environment [cyan]{env_name}[/cyan]...[/bold]"
    )

    try:
        if with_images:
            _prepare_images_for_deploy(config, project_dir, env_name)

        console.print(
            "[dim]Refreshing CloudFormation templates from darth-infra.toml...[/dim]"
        )
        generate_project(config, project_dir)

        lookups = resolve_lookup_data(config, env_name)
        validate_rendered_deploy_templates(project_dir, config, env_name, lookups)
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
            if with_images:
                _force_new_deployments_for_internal_services(config, env_name)
            seed_rc = run_seed_copy_tasks(config, env_name)
            if seed_rc != 0:
                console.print(
                    "[red]Infrastructure deploy succeeded, but one or more S3 seed-copy tasks failed.[/red]"
                )
                raise SystemExit(seed_rc)
            console.print(f"[green]✓ Deployed {env_name} successfully[/green]")
    else:
        console.print(f"[red]Deploy failed with exit code {rc}[/red]")
        raise SystemExit(rc)


def _prepare_images_for_deploy(config, project_dir, env_name: str) -> None:
    internal_services = select_internal_services(config, None)
    if not internal_services:
        console.print(
            "[dim]No internal service images to build/push for this deploy.[/dim]"
        )
        return

    if not _stack_exists(config.project_name, config.aws_region, env_name):
        console.print(
            "[bold]Bootstrapping ECR repositories with a zero-desired-count deploy...[/bold]"
        )
        bootstrap_config = copy.deepcopy(config)
        for service in bootstrap_config.services:
            if not service.image:
                service.desired_count = 0

        generate_project(bootstrap_config, project_dir)
        lookups = resolve_lookup_data(config, env_name)
        validate_rendered_deploy_templates(project_dir, bootstrap_config, env_name, lookups)
        bucket = ensure_artifact_bucket(config)
        packaged_template = package_template(project_dir, config, env_name, bucket)
        bootstrap_rc = deploy_changeset(
            config,
            env_name,
            packaged_template,
            lookups,
            no_execute=False,
            changeset_name=None,
        )
        if bootstrap_rc != 0:
            raise RuntimeError("bootstrap deploy failed")

    console.print("[bold]Building Docker images for deploy...[/bold]")
    build_images(config, project_dir, None)
    console.print("[bold]Pushing Docker images to ECR...[/bold]")
    push_images(config, env_name, None)


def _stack_exists(project_name: str, region: str, env_name: str) -> bool:
    stack_name = f"{project_name}-ecs-{env_name}"
    cf = boto3.client("cloudformation", region_name=region)
    try:
        cf.describe_stacks(StackName=stack_name)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        message = str(exc.response.get("Error", {}).get("Message", ""))
        if code == "ValidationError" and "does not exist" in message:
            return False
        raise


def _force_new_deployments_for_internal_services(config, env_name: str) -> None:
    services = select_internal_services(config, None)
    if not services:
        return

    ecs = boto3.client("ecs", region_name=config.aws_region)
    cluster_name = get_cluster_name(config.project_name, env_name)
    restarted: list[str] = []

    for service in services:
        service_name = get_service_name(config.project_name, env_name, service.name)
        try:
            ecs.update_service(
                cluster=cluster_name,
                service=service_name,
                forceNewDeployment=True,
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            message = str(exc.response.get("Error", {}).get("Message", ""))
            raise RuntimeError(
                f"Failed to restart ECS service '{service_name}' after image push ({code}): {message}"
            ) from exc
        restarted.append(service_name)

    console.print(
        "[green]✓ Forced ECS rollout for updated images:[/green] "
        + ", ".join(restarted)
    )
