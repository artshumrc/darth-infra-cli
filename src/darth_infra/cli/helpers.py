"""Shared CLI helpers."""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import boto3
from rich.console import Console

from ..config.loader import find_config, load_config
from ..config.models import (
    ActivePreviewEnvironment,
    EnvironmentOverride,
    ProjectConfig,
    S3BucketMode,
    SecretSource,
)
from .version_floor import enforce_cli_version_floor

console = Console()


def require_config() -> tuple[ProjectConfig, Path]:
    """Load config or exit with an error."""
    try:
        config_path = find_config()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    config = load_config(config_path)
    enforce_cli_version_floor(config)
    return config, config_path.parent


def resolve_environment_config(
    config: ProjectConfig,
    env_name: str,
    preview_from: str | None = None,
) -> ProjectConfig:
    """Return an effective config for a static or dynamic environment."""
    if not preview_from:
        if env_name not in config.environments:
            console.print(
                f"[red]Environment '{env_name}' not found in darth-infra.toml. "
                f"Available: {', '.join(config.environments)}[/red]"
            )
            raise SystemExit(1)
        resolved = copy.deepcopy(config)
        _apply_environment_overrides(resolved, env_name)
        _render_service_environment_templates(
            resolved,
            env_name,
            "",
            resolved.get_cluster_domain(env_name),
        )
        _render_external_secret_names(resolved, env_name)
        return resolved

    preview = config.preview_environments
    if not preview.enabled:
        console.print(
            "[red]Preview environments are not enabled in darth-infra.toml.[/red]"
        )
        raise SystemExit(1)
    if preview_from not in config.environments:
        console.print(
            f"[red]Preview base environment '{preview_from}' is not configured.[/red]"
        )
        raise SystemExit(1)
    if env_name == preview_from:
        console.print(
            "[red]Preview environment cannot equal its base environment.[/red]"
        )
        raise SystemExit(1)
    if preview_from != preview.base_environment:
        console.print(
            f"[red]Preview base must be '{preview.base_environment}' for this project.[/red]"
        )
        raise SystemExit(1)

    number = _extract_preview_number(env_name, preview.name_pattern)
    if number is None:
        console.print(
            f"[red]Preview environment '{env_name}' does not match name pattern "
            f"'{preview.name_pattern}'.[/red]"
        )
        raise SystemExit(1)

    resolved = copy.deepcopy(config)
    base_override = config.environment_overrides.get(preview_from)
    if base_override:
        resolved.environment_overrides[env_name] = EnvironmentOverride(
            instance_type_override=base_override.instance_type_override,
            ec2_instance_type_override=dict(base_override.ec2_instance_type_override),
            tags={},
        )
    domain = _render_preview_value(preview.domain_template, resolved, env_name, number)
    preview_tags = {
        "environment-type": "preview",
        "preview-base-environment": preview_from,
        "pull-request": number,
        "ephemeral-cleanup-id": f"{resolved.project_name}-{env_name}",
    }
    for key, value in preview.tags.items():
        rendered = _render_preview_value(value, resolved, env_name, number) or ""
        if rendered:
            preview_tags[key] = rendered

    resolved.active_preview = ActivePreviewEnvironment(
        env_name=env_name,
        base_environment=preview_from,
        number=number,
        domain=domain,
        hosted_zone_name=preview.hosted_zone_name,
        tags=preview_tags,
    )
    _resolve_preview_s3_fallback_buckets(resolved, preview_from)
    resolved._validate_preview_overlay_bucket_collisions()
    _apply_environment_overrides(resolved, preview_from)
    _render_service_environment_templates(resolved, env_name, number, domain)
    # A preview environment has no external secrets of its own, so `{env}`
    # names the base environment's, matching the S3 fallback overlay.
    _render_external_secret_names(resolved, preview_from)
    return resolved


def is_active_preview(config: ProjectConfig, env_name: str) -> bool:
    return bool(config.active_preview and config.active_preview.env_name == env_name)


def _extract_preview_number(env_name: str, pattern: str) -> str | None:
    escaped = re.escape(pattern).replace(r"\{number\}", r"(?P<number>[0-9]+)")
    match = re.fullmatch(escaped, env_name)
    if not match:
        return None
    return match.group("number")


def _render_preview_value(
    value: str | None,
    config: ProjectConfig,
    env_name: str,
    number: str,
) -> str | None:
    if value is None:
        return None
    return value.format(
        project=config.project_name,
        env=env_name,
        number=number,
        base_environment=config.preview_environments.base_environment,
    )


def _apply_environment_overrides(config: ProjectConfig, env_name: str) -> None:
    """Fold ``[environments.<env_name>]`` overrides into the config in place.

    Called once per env-scoped command, before templates are built, so the rest
    of the pipeline only ever sees effective values.
    """
    override = config.environment_overrides.get(env_name)
    if not override:
        return

    alb_override = override.alb
    if alb_override.shared_alb_name is not None:
        config.alb.shared_alb_name = alb_override.shared_alb_name
    if alb_override.shared_listener_arn is not None:
        config.alb.shared_listener_arn = alb_override.shared_listener_arn
    if alb_override.shared_alb_security_group_id is not None:
        config.alb.shared_alb_security_group_id = (
            alb_override.shared_alb_security_group_id
        )

    for service in config.services:
        service_override = override.services.get(service.name)
        if not service_override:
            continue
        if service_override.cpu is not None:
            service.cpu = service_override.cpu
        if service_override.memory_mib is not None:
            service.memory_mib = service_override.memory_mib
        if service_override.desired_count is not None:
            service.desired_count = service_override.desired_count
        service.environment_variables = {
            **service.environment_variables,
            **service_override.environment_variables,
        }


def _render_external_secret_names(config: ProjectConfig, env_name: str) -> None:
    """Substitute ``{project}`` and ``{env}`` in ``existing_secret_name``.

    Lets one ``[[secrets]]`` entry name a per-environment secret. An ARN or a
    name with no placeholder passes through unchanged.
    """
    replacements = {"project": config.project_name, "env": env_name}
    for secret in config.secrets:
        if secret.source != SecretSource.EXISTING or not secret.existing_secret_name:
            continue
        try:
            secret.existing_secret_name = secret.existing_secret_name.format(
                **replacements
            )
        except (KeyError, IndexError, ValueError):
            # Leave an unrecognized placeholder alone rather than guessing; the
            # deploy-time lookup reports the unresolvable name.
            continue


def _render_service_environment_templates(
    config: ProjectConfig,
    env_name: str,
    number: str,
    domain: str | None,
) -> None:
    service_discovery_suffix = ""
    service_discovery_namespace = config.get_service_discovery_namespace(env_name)
    replacements = {
        "project": config.project_name,
        "env": env_name,
        "number": number,
        "base_environment": config.preview_environments.base_environment,
        "domain": f"https://{domain}" if domain else "",
        "hostname": domain or "",
        "service_discovery_suffix": service_discovery_suffix,
        "service_discovery_namespace": service_discovery_namespace,
    }
    for service in config.services:
        rendered: dict[str, str] = {}
        for key, value in service.environment_variables.items():
            try:
                rendered[key] = value.format(**replacements)
            except (KeyError, ValueError):
                rendered[key] = value
        service.environment_variables = rendered


def _resolve_preview_s3_fallback_buckets(
    config: ProjectConfig, base_environment: str
) -> None:
    """Fill implicit preview S3 fallback buckets from the preview base env."""
    for bucket in config.s3_buckets:
        if not bucket.preview_fallback_env_key or bucket.preview_fallback_bucket_name:
            continue

        if bucket.mode == S3BucketMode.EXISTING:
            bucket.preview_fallback_bucket_name = bucket.existing_bucket_name
        else:
            bucket.preview_fallback_bucket_name = (
                f"{config.project_name}-{base_environment}-{bucket.name}"
            )


def require_prod_deployed(config: ProjectConfig, env: str) -> None:
    """Verify that the prod stack exists before deploying a non-prod env."""
    if env == "prod":
        return

    stack_name = f"{config.project_name}-ecs-prod"
    try:
        cf = boto3.client("cloudformation", region_name=config.aws_region)
        cf.describe_stacks(StackName=stack_name)
    except Exception:
        console.print(
            f"[red]Prod stack '{stack_name}' must be deployed before "
            f"deploying '{env}'. Run: darth-infra deploy --env prod[/red]"
        )
        sys.exit(1)


def get_cluster_name(project_name: str, env: str) -> str:
    return f"{project_name}-{env}"


def get_service_name(project_name: str, env: str, service: str) -> str:
    return f"{project_name}-{env}-{service}"
