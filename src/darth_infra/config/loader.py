"""Load and save ProjectConfig from/to darth-infra.toml."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from .models import (
    AlbConfig,
    AlbMode,
    AlbPathRule,
    Architecture,
    EbsVolumeConfig,
    EnvironmentOverride,
    LaunchType,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
    UlimitConfig,
)

CONFIG_FILENAME = "darth-infra.toml"


def _toml_escape(value: str) -> str:
    """Escape a string value for safe inclusion in TOML double quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_multiline(value: str) -> str:
    """Render a string as a TOML multiline basic string."""
    return '"""\n' + value.replace('"""', '\\"""') + '\n"""'


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def find_config(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find ``darth-infra.toml``."""
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
    """Parse ``darth-infra.toml`` into a ``ProjectConfig``."""
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
        vpc_id=project.get("vpc_id"),
        private_subnet_ids=project.get("private_subnet_ids", []),
        public_subnet_ids=project.get("public_subnet_ids", []),
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
    if "domain" in raw:
        raise ValueError(
            "services[].domain is no longer supported; use alb.domain and alb routing fields"
        )
    # Port defaults to None if not explicitly set (background workers have no port)
    port = raw.get("port")
    launch_type_str = raw.get("launch_type", "fargate")
    ebs_raw = raw.get("ebs_volumes", [])
    ebs_volumes = [
        EbsVolumeConfig(
            name=v["name"],
            size_gb=v["size_gb"],
            mount_path=v["mount_path"],
            device_name=v.get("device_name", "/dev/xvdf"),
            volume_type=v.get("volume_type", "gp3"),
            filesystem_type=v.get("filesystem_type", "ext4"),
        )
        for v in ebs_raw
    ]
    ulimits_raw = raw.get("ulimits", [])
    ulimits = [
        UlimitConfig(
            name=u["name"],
            soft_limit=u["soft_limit"],
            hard_limit=u["hard_limit"],
        )
        for u in ulimits_raw
    ]
    arch_str = raw.get("architecture")
    architecture = Architecture(arch_str) if arch_str else None
    return ServiceConfig(
        name=raw["name"],
        dockerfile=raw.get("dockerfile", "Dockerfile"),
        build_context=raw.get("build_context", "."),
        image=raw.get("image"),
        port=port,
        health_check_path=raw.get("health_check_path", "/health"),
        health_check_http_codes=raw.get("health_check_http_codes", "200-399"),
        health_check_timeout_seconds=raw.get("health_check_timeout_seconds", 5),
        health_check_interval_seconds=raw.get("health_check_interval_seconds", 30),
        healthy_threshold_count=raw.get("healthy_threshold_count", 5),
        unhealthy_threshold_count=raw.get("unhealthy_threshold_count", 2),
        health_check_grace_period_seconds=raw.get("health_check_grace_period_seconds"),
        cpu=raw.get("cpu", 256),
        memory_mib=raw.get("memory_mib", 512),
        desired_count=raw.get("desired_count", 1),
        command=raw.get("command"),
        secrets=raw.get("secrets", []),
        s3_access=raw.get("s3_access", []),
        environment_variables=raw.get("environment_variables", {}),
        ulimits=ulimits,
        enable_exec=raw.get("enable_exec", True),
        launch_type=LaunchType(launch_type_str),
        ec2_instance_type=raw.get("ec2_instance_type"),
        architecture=architecture,
        user_data_script=raw.get("user_data_script"),
        user_data_script_content=raw.get("user_data_script_content"),
        ebs_volumes=ebs_volumes,
        enable_service_discovery=raw.get("enable_service_discovery", False),
    )


def _parse_rds(raw: dict[str, Any]) -> RdsConfig:
    return RdsConfig(
        database_name=raw.get("database_name", "app"),
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
        shared_listener_arn=raw.get("shared_listener_arn"),
        shared_alb_security_group_id=raw.get("shared_alb_security_group_id"),
        certificate_arn=raw.get("certificate_arn"),
        domain=raw.get("domain"),
        default_target_service=raw.get("default_target_service"),
        default_listener_priority=raw.get("default_listener_priority"),
        path_rules=[
            AlbPathRule(
                name=str(rule["name"]),
                path_pattern=str(rule["path_pattern"]),
                target_service=str(rule["target_service"]),
                priority=int(rule["priority"]),
            )
            for rule in raw.get("path_rules", [])
        ],
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
        instance_type_override=raw.get("instance_type_override"),
        ec2_instance_type_override=raw.get("ec2_instance_type_override", {}),
    )


def dump_config(config: ProjectConfig) -> str:
    """Serialize a ``ProjectConfig`` to TOML string."""
    lines: list[str] = []

    lines.append("#:schema darth-infra.schema.json")
    lines.append("#")
    lines.append("# darth-infra config")
    lines.append("#")
    lines.append("# Full wizard answers and incomplete draft input are stored in")
    lines.append("# wizard-export.json. This TOML remains the main editable config.")
    lines.append("")
    lines.append("# [deploy-live] project and network lookup settings")
    lines.append("[project]")
    lines.append(f'name = "{config.project_name}"')
    lines.append(f'aws_region = "{config.aws_region}"')
    lines.append(f'vpc_name = "{config.vpc_name}"')
    if config.vpc_id:
        lines.append(f'vpc_id = "{config.vpc_id}"')
    if config.private_subnet_ids:
        subnet_list = ", ".join(f'"{s}"' for s in config.private_subnet_ids)
        lines.append(f"private_subnet_ids = [{subnet_list}]")
    if config.public_subnet_ids:
        subnet_list = ", ".join(f'"{s}"' for s in config.public_subnet_ids)
        lines.append(f"public_subnet_ids = [{subnet_list}]")
    env_list = ", ".join(f'"{e}"' for e in config.environments)
    lines.append(f"environments = [{env_list}]")
    if config.tags:
        lines.append("")
        lines.append("[project.tags]")
        for k, v in config.tags.items():
            lines.append(f'"{k}" = "{v}"')
    lines.append("")

    lines.append("# Service runtime settings")
    for svc in config.services:
        lines.append("[[services]]")
        lines.append(f'name = "{svc.name}"')
        lines.append(f'dockerfile = "{svc.dockerfile}"')
        lines.append(f'build_context = "{svc.build_context}"')
        if svc.image:
            lines.append(f'image = "{svc.image}"')
        if svc.port is not None:
            lines.append(f"port = {svc.port}")
        else:
            lines.append("# port omitted for worker service")
        lines.append(f'health_check_path = "{svc.health_check_path}"')
        lines.append(f'health_check_http_codes = "{svc.health_check_http_codes}"')
        lines.append(f"health_check_timeout_seconds = {svc.health_check_timeout_seconds}")
        lines.append(f"health_check_interval_seconds = {svc.health_check_interval_seconds}")
        lines.append(f"healthy_threshold_count = {svc.healthy_threshold_count}")
        lines.append(f"unhealthy_threshold_count = {svc.unhealthy_threshold_count}")
        if svc.health_check_grace_period_seconds is not None:
            lines.append(
                f"health_check_grace_period_seconds = {svc.health_check_grace_period_seconds}"
            )
        lines.append(f"cpu = {svc.cpu}")
        lines.append(f"memory_mib = {svc.memory_mib}")
        lines.append(f"desired_count = {svc.desired_count}")
        if svc.command:
            lines.append(f'command = "{_toml_escape(svc.command)}"')
        lines.append(f'launch_type = "{_enum_value(svc.launch_type)}"')
        if svc.ec2_instance_type:
            lines.append(f'ec2_instance_type = "{svc.ec2_instance_type}"')
        if svc.architecture:
            lines.append(f'architecture = "{_enum_value(svc.architecture)}"')
        if svc.user_data_script:
            lines.append(f'user_data_script = "{svc.user_data_script}"')
        if svc.user_data_script_content:
            lines.append(
                f"user_data_script_content = {_toml_multiline(svc.user_data_script_content)}"
            )
        if svc.secrets:
            sec_list = ", ".join(f'"{s}"' for s in svc.secrets)
            lines.append(f"secrets = [{sec_list}]")
        if svc.s3_access:
            s3_list = ", ".join(f'"{s}"' for s in svc.s3_access)
            lines.append(f"s3_access = [{s3_list}]")
        if svc.environment_variables:
            env_inline = ", ".join(
                f'"{k}" = "{_toml_escape(v)}"'
                for k, v in svc.environment_variables.items()
            )
            lines.append(f"environment_variables = {{ {env_inline} }}")
        lines.append(f"enable_exec = {str(svc.enable_exec).lower()}")
        lines.append(
            f"enable_service_discovery = {str(svc.enable_service_discovery).lower()}"
        )
        for ul in svc.ulimits:
            lines.append("")
            lines.append("[[services.ulimits]]")
            lines.append(f'name = "{ul.name}"')
            lines.append(f"soft_limit = {ul.soft_limit}")
            lines.append(f"hard_limit = {ul.hard_limit}")
        for vol in svc.ebs_volumes:
            lines.append("")
            lines.append("[[services.ebs_volumes]]")
            lines.append(f'name = "{vol.name}"')
            lines.append(f"size_gb = {vol.size_gb}")
            lines.append(f'mount_path = "{vol.mount_path}"')
            lines.append(f'device_name = "{vol.device_name}"')
            lines.append(f'volume_type = "{vol.volume_type}"')
            lines.append(f'filesystem_type = "{vol.filesystem_type}"')
        lines.append("")

    if config.rds:
        lines.append("# Optional RDS")
        lines.append("[rds]")
        lines.append(f'database_name = "{config.rds.database_name}"')
        lines.append(f'instance_type = "{config.rds.instance_type}"')
        lines.append(f"allocated_storage_gb = {config.rds.allocated_storage_gb}")
        expose_list = ", ".join(f'"{s}"' for s in config.rds.expose_to)
        lines.append(f"expose_to = [{expose_list}]")
        lines.append(f'engine_version = "{config.rds.engine_version}"')
        lines.append(f"backup_retention_days = {config.rds.backup_retention_days}")
        lines.append("")

    if config.s3_buckets:
        lines.append("# Optional S3 buckets")
    for bucket in config.s3_buckets:
        lines.append("[[s3_buckets]]")
        lines.append(f'name = "{bucket.name}"')
        lines.append(f"public_read = {str(bucket.public_read).lower()}")
        lines.append(f"cloudfront = {str(bucket.cloudfront).lower()}")
        lines.append(f"cors = {str(bucket.cors).lower()}")
        lines.append("")

    lines.append("# [deploy-live] ALB lookup/attachment behavior")
    lines.append("[alb]")
    lines.append(f'mode = "{_enum_value(config.alb.mode)}"')
    lines.append(f'shared_alb_name = "{config.alb.shared_alb_name}"')
    if config.alb.shared_listener_arn:
        lines.append(f'shared_listener_arn = "{config.alb.shared_listener_arn}"')
    if config.alb.shared_alb_security_group_id:
        lines.append(
            f'shared_alb_security_group_id = "{config.alb.shared_alb_security_group_id}"'
        )
    if config.alb.certificate_arn:
        lines.append(f'certificate_arn = "{config.alb.certificate_arn}"')
    if config.alb.domain:
        lines.append(f'domain = "{config.alb.domain}"')
    if config.alb.default_target_service:
        lines.append(f'default_target_service = "{config.alb.default_target_service}"')
    if config.alb.default_listener_priority is not None:
        lines.append(f"default_listener_priority = {config.alb.default_listener_priority}")
    for rule in config.alb.path_rules:
        lines.append("")
        lines.append("[[alb.path_rules]]")
        lines.append(f'name = "{rule.name}"')
        lines.append(f'path_pattern = "{rule.path_pattern}"')
        lines.append(f'target_service = "{rule.target_service}"')
        lines.append(f"priority = {rule.priority}")
    lines.append("")

    if config.secrets:
        lines.append("# Secrets")
    for secret in config.secrets:
        lines.append("[[secrets]]")
        lines.append(f'name = "{secret.name}"')
        lines.append(f'source = "{_enum_value(secret.source)}"')
        lines.append(f"length = {secret.length}")
        lines.append(f"generate_once = {str(secret.generate_once).lower()}")
        lines.append("")
    if not config.secrets:
        lines.append("# No secrets configured")
        lines.append("")

    if config.environment_overrides:
        lines.append("# [deploy-live] environment-specific runtime overrides")
    for env_name, override in config.environment_overrides.items():
        lines.append(f"[environments.{env_name}]")
        if override.instance_type_override:
            lines.append(
                f'instance_type_override = "{override.instance_type_override}"'
            )
        if override.ec2_instance_type_override:
            lines.append("")
            lines.append(f"[environments.{env_name}.ec2_instance_type_override]")
            for svc_name, itype in override.ec2_instance_type_override.items():
                lines.append(f'{svc_name} = "{itype}"')
        lines.append("")
    if not config.environment_overrides:
        lines.append("# [deploy-live] no [environments.<name>] overrides configured")
        lines.append("")

    return "\n".join(lines) + "\n"
