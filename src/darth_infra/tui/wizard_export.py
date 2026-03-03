"""Wizard state helpers for defaulting and TOML rehydration."""

from __future__ import annotations

from typing import Any

from ..config.models import ProjectConfig


def default_wizard_state() -> dict[str, Any]:
    """Default mutable wizard state shared across TUI screens."""
    return {
        "project_name": "",
        "vpc_name": "artshumrc-prod-standard",
        "aws_region": "us-east-1",
        "environments": ["prod"],
        "services": [],
        "rds": None,
        "s3_buckets": [],
        "cloudfront_enabled": False,
        "cloudfront_origin_https_only": False,
        "cloudfront_custom_domain": None,
        "cloudfront_certificate_arn": None,
        "cloudfront_price_class": "PriceClass_100",
        "cloudfront_comment": None,
        "cloudfront_connections": [],
        "cloudfront_cached_behaviors": [],
        "alb_mode": "shared",
        "shared_alb_name": "",
        "shared_listener_arn": None,
        "shared_listener_protocol": None,
        "shared_listener_port": None,
        "shared_alb_security_group_id": None,
        "certificate_arn": None,
        "alb_domain": None,
        "default_target_service": None,
        "default_listener_priority": None,
        "alb_path_rules": [],
        "secrets": [],
        "_wizard_draft": {},
        "_wizard_last_screen": "welcome",
    }


def merge_seed_state(seed: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a seed export state into defaults (best-effort, non-strict)."""
    state = default_wizard_state()
    if not isinstance(seed, dict):
        return state

    for key in state:
        if key in seed:
            state[key] = seed[key]

    # Preserve extra keys too, to avoid dropping future draft fields.
    for key, value in seed.items():
        if key not in state:
            state[key] = value

    if not isinstance(state.get("_wizard_draft"), dict):
        state["_wizard_draft"] = {}
    else:
        # Service draft data is highly contextual to the last focused item and
        # can corrupt resumed edits when real services already exist.
        if state.get("services"):
            state["_wizard_draft"].pop("services", None)
    if not isinstance(state.get("_wizard_last_screen"), str):
        state["_wizard_last_screen"] = "welcome"

    return state


def project_config_to_wizard_state(config: ProjectConfig) -> dict[str, Any]:
    """Convert ProjectConfig into wizard state values for rehydration."""
    base = default_wizard_state()

    services: list[dict[str, Any]] = []
    for svc in config.services:
        services.append(
            {
                "name": svc.name,
                "dockerfile": svc.dockerfile,
                "build_context": svc.build_context,
                "docker_build_target": svc.docker_build_target,
                "image": svc.image,
                "port": svc.port,
                "health_check_path": svc.health_check_path,
                "health_check_http_codes": svc.health_check_http_codes,
                "health_check_timeout_seconds": svc.health_check_timeout_seconds,
                "health_check_interval_seconds": svc.health_check_interval_seconds,
                "healthy_threshold_count": svc.healthy_threshold_count,
                "unhealthy_threshold_count": svc.unhealthy_threshold_count,
                "health_check_grace_period_seconds": svc.health_check_grace_period_seconds,
                "cpu": svc.cpu,
                "memory_mib": svc.memory_mib,
                "desired_count": svc.desired_count,
                "command": svc.command,
                "secrets": list(svc.secrets),
                "launch_type": str(getattr(svc.launch_type, "value", svc.launch_type)),
                "ec2_instance_type": svc.ec2_instance_type,
                "user_data_script": svc.user_data_script,
                "user_data_script_content": svc.user_data_script_content,
                "ebs_volumes": [
                    {
                        "name": vol.name,
                        "size_gb": vol.size_gb,
                        "mount_path": vol.mount_path,
                        "device_name": vol.device_name,
                        "volume_type": vol.volume_type,
                        "filesystem_type": vol.filesystem_type,
                    }
                    for vol in svc.ebs_volumes
                ],
                "ulimits": [
                    {
                        "name": ul.name,
                        "soft_limit": ul.soft_limit,
                        "hard_limit": ul.hard_limit,
                    }
                    for ul in svc.ulimits
                ],
                "environment_variables": dict(svc.environment_variables),
                "enable_service_discovery": svc.enable_service_discovery,
            }
        )

    s3_buckets: list[dict[str, Any]] = []
    for bucket in config.s3_buckets:
        s3_buckets.append(
            {
                "name": bucket.name,
                "mode": str(getattr(bucket.mode, "value", bucket.mode)),
                "existing_bucket_name": bucket.existing_bucket_name,
                "seed_source_bucket_name": bucket.seed_source_bucket_name,
                "seed_non_prod_only": bucket.seed_non_prod_only,
                "public_read": bucket.public_read,
                "cloudfront": bucket.cloudfront,
                "cors": bucket.cors,
                "connections": [
                    {
                        "service": conn.service,
                        "env_key": conn.env_key,
                        "cloudfront_env_key": conn.cloudfront_env_key,
                        "read_only": conn.read_only,
                    }
                    for conn in bucket.connections
                ],
            }
        )

    secrets: list[dict[str, Any]] = []
    for sec in config.secrets:
        secrets.append(
            {
                "name": sec.name,
                "source": str(getattr(sec.source, "value", sec.source)),
                "existing_secret_name": sec.existing_secret_name,
                "length": sec.length,
                "generate_once": sec.generate_once,
            }
        )

    base.update(
        {
            "project_name": config.project_name,
            "aws_region": config.aws_region,
            "vpc_name": config.vpc_name,
            "vpc_id": config.vpc_id,
            "private_subnet_ids": list(config.private_subnet_ids),
            "public_subnet_ids": list(config.public_subnet_ids),
            "environments": list(config.environments),
            "services": services,
            "rds": (
                None
                if config.rds is None
                else {
                    "database_name": config.rds.database_name,
                    "instance_type": config.rds.instance_type,
                    "allocated_storage_gb": config.rds.allocated_storage_gb,
                    "expose_to": list(config.rds.expose_to),
                    "engine_version": config.rds.engine_version,
                    "backup_retention_days": config.rds.backup_retention_days,
                }
            ),
            "s3_buckets": s3_buckets,
            "cloudfront_enabled": config.cloudfront.enabled,
            "cloudfront_origin_https_only": config.cloudfront.origin_https_only,
            "cloudfront_custom_domain": config.cloudfront.custom_domain,
            "cloudfront_certificate_arn": config.cloudfront.certificate_arn,
            "cloudfront_price_class": config.cloudfront.price_class,
            "cloudfront_comment": config.cloudfront.comment,
            "cloudfront_connections": [
                {"service": conn.service, "env_key": conn.env_key}
                for conn in config.cloudfront.connections
            ],
            "cloudfront_cached_behaviors": [
                {
                    "name": behavior.name,
                    "path_pattern": behavior.path_pattern,
                    "compress": behavior.compress,
                    "cache_by_origin_headers": behavior.cache_by_origin_headers,
                    "min_ttl_seconds": behavior.min_ttl_seconds,
                    "default_ttl_seconds": behavior.default_ttl_seconds,
                    "max_ttl_seconds": behavior.max_ttl_seconds,
                    "query_strings": str(
                        getattr(behavior.query_strings, "value", behavior.query_strings)
                    ),
                    "query_string_allowlist": list(
                        behavior.query_string_allowlist
                    ),
                    "cookies": str(getattr(behavior.cookies, "value", behavior.cookies)),
                    "cookie_allowlist": list(behavior.cookie_allowlist),
                    "forward_authorization_header": behavior.forward_authorization_header,
                }
                for behavior in config.cloudfront.cached_behaviors
            ],
            "alb_mode": "shared",
            "shared_alb_name": config.alb.shared_alb_name,
            "shared_listener_arn": config.alb.shared_listener_arn,
            "shared_listener_protocol": None,
            "shared_listener_port": None,
            "shared_alb_security_group_id": config.alb.shared_alb_security_group_id,
            "certificate_arn": config.alb.certificate_arn,
            "alb_domain": config.alb.domain,
            "default_target_service": config.alb.default_target_service,
            "default_listener_priority": config.alb.default_listener_priority,
            "alb_path_rules": [
                {
                    "name": rule.name,
                    "path_pattern": rule.path_pattern,
                    "target_service": rule.target_service,
                    "priority": rule.priority,
                }
                for rule in config.alb.path_rules
            ],
            "secrets": secrets,
            "_wizard_draft": {},
            "_wizard_last_screen": "welcome",
            "_wizard_max_step_index": 0,
        }
    )

    return base
