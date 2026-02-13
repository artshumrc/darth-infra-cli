from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from ...config.models import (
    AlbConfig,
    AlbMode,
    EnvironmentOverride,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)

CONFIG_FILENAME = "darth-ecs.toml"


def find_config(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find ``darth-ecs.toml``."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                f"Could not find {CONFIG_FILENAME} in {start or Path.cwd()} "
                f"or any parent directory"
            )
        current = parent


def load_config(path: Path | None = None) -> ProjectConfig:
    """Parse ``darth-ecs.toml`` into a ``ProjectConfig``."""
    config_path = path or find_config()
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    return _parse_project(raw)


def _parse_project(raw: dict[str, Any]) -> ProjectConfig:
    project = raw.get("project", {})
    services_raw = raw.get("services", [])
    rds_raw = raw.get("rds")
    s3_raw = raw.get("s3_buckets", [])
    alb_raw = raw.get("alb", {})
    secrets_raw = raw.get("secrets", [])
    env_overrides_raw = raw.get("environments", {})

    services = [_parse_service(s) for s in services_raw]
    rds = _parse_rds(rds_raw) if rds_raw else None
    s3_buckets = [_parse_s3(b) for b in s3_raw]
    alb = _parse_alb(alb_raw)
    secrets = [_parse_secret(s) for s in secrets_raw]
    environment_overrides = {
        name: _parse_env_override(data)
        for name, data in env_overrides_raw.items()
        if isinstance(data, dict)
    }

    return ProjectConfig(
        project_name=project["name"],
        aws_region=project.get("aws_region", "us-east-1"),
        vpc_name=project.get("vpc_name", "artshumrc-prod-standard"),
        environments=project.get("environments", ["prod"]),
        tags=project.get("tags", {}),
        services=services,
        rds=rds,
        s3_buckets=s3_buckets,
        alb=alb,
        secrets=secrets,
        environment_overrides=environment_overrides,
    )


def _parse_service(raw: dict[str, Any]) -> ServiceConfig:
    return ServiceConfig(
        name=raw["name"],
        dockerfile=raw.get("dockerfile", "Dockerfile"),
        build_context=raw.get("build_context", "."),
        port=raw.get("port", 8000),
        health_check_path=raw.get("health_check_path", "/health"),
        cpu=raw.get("cpu", 256),
        memory_mib=raw.get("memory_mib", 512),
        desired_count=raw.get("desired_count", 1),
        command=raw.get("command"),
        domain=raw.get("domain"),
        secrets=raw.get("secrets", []),
        s3_access=raw.get("s3_access", []),
        environment_variables=raw.get("environment_variables", {}),
        enable_exec=raw.get("enable_exec", True),
    )


def _parse_rds(raw: dict[str, Any]) -> RdsConfig:
    return RdsConfig(
        database_name=raw["database_name"],
        instance_type=raw.get("instance_type", "t4g.micro"),
        allocated_storage_gb=raw.get("allocated_storage_gb", 20),
        expose_to=raw.get("expose_to", []),
        engine_version=raw.get("engine_version", "15"),
        backup_retention_days=raw.get("backup_retention_days", 7),
    )


def _parse_s3(raw: dict[str, Any]) -> S3BucketConfig:
    return S3BucketConfig(
        name=raw["name"],
        public_read=raw.get("public_read", False),
        cloudfront=raw.get("cloudfront", False),
        cors=raw.get("cors", False),
    )


def _parse_alb(raw: dict[str, Any]) -> AlbConfig:
    mode_str = raw.get("mode", "shared")
    return AlbConfig(
        mode=AlbMode(mode_str),
        shared_alb_name=raw.get("shared_alb_name", ""),
        certificate_arn=raw.get("certificate_arn"),
    )


def _parse_secret(raw: dict[str, Any]) -> SecretConfig:
    source_str = raw.get("source", "generate")
    return SecretConfig(
        name=raw["name"],
        source=SecretSource(source_str),
        length=raw.get("length", 50),
        generate_once=raw.get("generate_once", True),
    )


def _parse_env_override(raw: dict[str, Any]) -> EnvironmentOverride:
    return EnvironmentOverride(
        domain_overrides=raw.get("domain_overrides", {}),
        instance_type_override=raw.get("instance_type_override"),
    )


def dump_config(config: ProjectConfig) -> str:
    """Serialize a ``ProjectConfig`` to TOML string."""
    lines: list[str] = []

    lines.append("[project]")
    lines.append(f'name = "{config.project_name}"')
    lines.append(f'aws_region = "{config.aws_region}"')
    lines.append(f'vpc_name = "{config.vpc_name}"')
    env_list = ", ".join(f'"{e}"' for e in config.environments)
    lines.append(f"environments = [{env_list}]")
    if config.tags:
        lines.append("")
        lines.append("[project.tags]")
        for k, v in config.tags.items():
            lines.append(f'"{k}" = "{v}"')
    lines.append("")

    for svc in config.services:
        lines.append("[[services]]")
        lines.append(f'name = "{svc.name}"')
        lines.append(f'dockerfile = "{svc.dockerfile}"')
        lines.append(f'build_context = "{svc.build_context}"')
        if svc.port is not None:
            lines.append(f"port = {svc.port}")
        else:
            lines.append("# port not set — this is a background worker")
        lines.append(f'health_check_path = "{svc.health_check_path}"')
        lines.append(f"cpu = {svc.cpu}")
        lines.append(f"memory_mib = {svc.memory_mib}")
        lines.append(f"desired_count = {svc.desired_count}")
        if svc.command:
            lines.append(f'command = "{svc.command}"')
        if svc.domain:
            lines.append(f'domain = "{svc.domain}"')
        if svc.secrets:
            sec_list = ", ".join(f'"{s}"' for s in svc.secrets)
            lines.append(f"secrets = [{sec_list}]")
        if svc.s3_access:
            s3_list = ", ".join(f'"{s}"' for s in svc.s3_access)
            lines.append(f"s3_access = [{s3_list}]")
        if svc.environment_variables:
            lines.append("")
            lines.append(f"[services.{svc.name}.environment_variables]")
            for k, v in svc.environment_variables.items():
                lines.append(f'"{k}" = "{v}"')
        lines.append(f"enable_exec = {str(svc.enable_exec).lower()}")
        lines.append("")

    if config.rds:
        lines.append("[rds]")
        lines.append(f'database_name = "{config.rds.database_name}"')
        lines.append(f'instance_type = "{config.rds.instance_type}"')
        lines.append(f"allocated_storage_gb = {config.rds.allocated_storage_gb}")
        expose_list = ", ".join(f'"{s}"' for s in config.rds.expose_to)
        lines.append(f"expose_to = [{expose_list}]")
        lines.append(f'engine_version = "{config.rds.engine_version}"')
        lines.append(f"backup_retention_days = {config.rds.backup_retention_days}")
        lines.append("")

    for bucket in config.s3_buckets:
        lines.append("[[s3_buckets]]")
        lines.append(f'name = "{bucket.name}"')
        lines.append(f"public_read = {str(bucket.public_read).lower()}")
        lines.append(f"cloudfront = {str(bucket.cloudfront).lower()}")
        lines.append(f"cors = {str(bucket.cors).lower()}")
        lines.append("")

    lines.append("[alb]")
    lines.append(f'mode = "{config.alb.mode.value}"')
    lines.append(f'shared_alb_name = "{config.alb.shared_alb_name}"')
    if config.alb.certificate_arn:
        lines.append(f'certificate_arn = "{config.alb.certificate_arn}"')
    lines.append("")

    for secret in config.secrets:
        lines.append("[[secrets]]")
        lines.append(f'name = "{secret.name}"')
        lines.append(f'source = "{secret.source.value}"')
        lines.append(f"length = {secret.length}")
        lines.append(f"generate_once = {str(secret.generate_once).lower()}")
        lines.append("")

    for env_name, override in config.environment_overrides.items():
        lines.append(f"[environments.{env_name}]")
        if override.domain_overrides:
            lines.append("")
            lines.append(f"[environments.{env_name}.domain_overrides]")
            for svc_name, domain in override.domain_overrides.items():
                lines.append(f'{svc_name} = "{domain}"')
        if override.instance_type_override:
            lines.append(
                f'instance_type_override = "{override.instance_type_override}"'
            )
        lines.append("")

    return "\n".join(lines) + "\n"
