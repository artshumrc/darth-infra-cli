"""Scaffold generator — renders CloudFormation templates into a project directory."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..config.models import ProjectConfig

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "cfn"


def _pascalize(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _resolve_user_data_script_content(
    inline: str | None, path: str | None
) -> str | None:
    content = (inline or "").strip()
    if not content and path:
        src_script = Path.cwd() / path
        if src_script.is_file():
            content = src_script.read_text().strip()
    if not content:
        return None
    # Escape Fn::Sub interpolation markers from user-provided script content.
    return content.replace("${", "$${")


def _derive_rds_master_username(database_name: str) -> str:
    """Derive a safe RDS master username from database name.

    RDS DB master usernames must start with a letter and contain only
    alphanumeric characters, with max length 16.
    """
    normalized = re.sub(r"[^A-Za-z0-9]", "", database_name)
    if not normalized:
        normalized = "appuser"
    if not normalized[0].isalpha():
        normalized = f"u{normalized}"
    return normalized[:16].lower()


def _normalize_rds_json_key(value: str | None) -> str | None:
    """Normalize RDS JSON key aliases/display labels to canonical keys."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw in {"host", "port", "dbname", "username", "password"}:
        return raw

    lowered = raw.lower().strip()
    if lowered.startswith("rds"):
        lowered = lowered[3:].strip()
    compact = "".join(ch for ch in lowered if ch.isalnum())

    aliases = {
        "host": "host",
        "port": "port",
        "dbname": "dbname",
        "database": "dbname",
        "databasename": "dbname",
        "db": "dbname",
        "user": "username",
        "username": "username",
        "pass": "password",
        "password": "password",
    }
    return aliases.get(compact, raw)


def generate_project(config: ProjectConfig, output_dir: Path) -> Path:
    """Render the full CloudFormation project into *output_dir*.

    Returns the output directory path.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    jinja_env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    ctx = _build_context(config)

    # Top-level project docs + source config
    _render(jinja_env, "README.md.j2", output_dir / "README.md", ctx)

    from ..config.loader import dump_config

    toml_path = output_dir / "darth-infra.toml"
    toml_path.write_text(dump_config(config))

    # Copy the JSON schema for editor support
    schema_src = Path(__file__).resolve().parent.parent / "darth-infra.schema.json"
    if schema_src.exists():
        schema_dest = output_dir / "darth-infra.schema.json"
        if schema_src.resolve() != schema_dest.resolve():
            shutil.copy2(schema_src, schema_dest)

    templates_dir = output_dir / "templates"
    generated_dir = templates_dir / "generated"
    services_dir = generated_dir / "services"
    custom_dir = templates_dir / "custom"
    services_dir.mkdir(parents=True, exist_ok=True)
    custom_dir.mkdir(parents=True, exist_ok=True)

    _render(jinja_env, "root.yaml.j2", generated_dir / "root.yaml", ctx)

    for svc_ctx in ctx["services_ctx"]:
        _render(
            jinja_env,
            "nested/service.yaml.j2",
            services_dir / f"{svc_ctx['name']}.yaml",
            {**ctx, **svc_ctx},
        )

    # Do not overwrite user-owned custom overrides template once created.
    custom_overrides = custom_dir / "overrides.yaml"
    if not custom_overrides.exists():
        _render(jinja_env, "custom/overrides.yaml.j2", custom_overrides, ctx)

    # Copy user data scripts for EC2 services
    for svc in config.services:
        if svc.user_data_script:
            src_script = (Path.cwd() / svc.user_data_script).resolve()
            if src_script.is_file():
                dest_script = (output_dir / svc.user_data_script).resolve()
                dest_script.parent.mkdir(parents=True, exist_ok=True)
                if src_script == dest_script:
                    continue
                try:
                    shutil.copy2(src_script, dest_script)
                except shutil.SameFileError:
                    continue

    return output_dir


def _build_context(config: ProjectConfig) -> dict:
    services_ctx: list[dict[str, object]] = []
    alb_target_services: dict[str, dict[str, str]] = {}
    routed_alb_target_services: set[str] = set()
    if config.alb.domain:
        if config.alb.default_target_service:
            routed_alb_target_services.add(config.alb.default_target_service)
        for rule in config.alb.path_rules:
            routed_alb_target_services.add(rule.target_service)
    rds_expose_to = set(config.rds.expose_to if config.rds else [])
    rds_secret_key_by_env = {
        "DATABASE_HOST": "host",
        "DATABASE_PORT": "port",
        "DATABASE_DB": "dbname",
        "DATABASE_USER": "username",
        "DATABASE_PASSWORD": "password",
        "POSTGRES_HOST": "host",
        "POSTGRES_PORT": "port",
        "POSTGRES_DB": "dbname",
        "POSTGRES_USER": "username",
        "POSTGRES_PASSWORD": "password",
    }
    required_postgres_secret_names = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    )
    secrets_by_name = {sec.name: sec for sec in config.secrets}

    s3_access_by_service: dict[str, list[dict]] = {}
    seen_s3_entries_by_service: dict[str, set[tuple[str, str, str | None, bool]]] = {}
    for bucket in config.s3_buckets:
        bucket_ref = (
            f"Bucket{bucket.name.replace('-', '')}"
            if bucket.mode.value != "existing"
            else None
        )
        bucket_name_literal = (
            bucket.existing_bucket_name if bucket.mode.value == "existing" else None
        )
        for conn in bucket.connections:
            dedupe_key = (
                bucket.name,
                conn.env_key,
                conn.cloudfront_env_key,
                conn.read_only,
            )
            seen_for_service = seen_s3_entries_by_service.setdefault(
                conn.service, set()
            )
            if dedupe_key in seen_for_service:
                continue
            seen_for_service.add(dedupe_key)
            s3_access_by_service.setdefault(conn.service, []).append(
                {
                    "bucket_name": bucket.name,
                    "bucket_ref": bucket_ref,
                    "bucket_name_literal": bucket_name_literal,
                    "env_key": conn.env_key,
                    "param_name": f"BucketName{_pascalize(bucket.name)}",
                    "arn_param_name": f"BucketArn{_pascalize(bucket.name)}",
                    "cf_param_name": f"CloudFrontUrl{_pascalize(bucket.name)}"
                    if (
                        bucket.cloudfront
                        and conn.cloudfront_env_key
                        and bucket.mode.value != "existing"
                    )
                    else None,
                    "cloudfront_env_key": conn.cloudfront_env_key
                    if bucket.cloudfront
                    else None,
                    "read_only": conn.read_only,
                }
            )

    for service_name, entries in s3_access_by_service.items():
        s3_access_by_service[service_name] = sorted(
            entries,
            key=lambda item: (
                str(item["bucket_name"]),
                str(item["env_key"]),
                str(item.get("cloudfront_env_key") or ""),
            ),
        )

    cloudfront_access_by_service: dict[str, list[dict[str, str]]] = {}
    for conn in config.cloudfront.connections:
        cloudfront_access_by_service.setdefault(conn.service, []).append(
            {
                "env_key": conn.env_key,
                "param_name": f"CloudFrontUrl{_pascalize(conn.env_key)}",
            }
        )
    for service_name, entries in cloudfront_access_by_service.items():
        seen_param_names: set[str] = set()
        deduped: list[dict[str, str]] = []
        for entry in entries:
            key = entry["param_name"]
            if key in seen_param_names:
                continue
            seen_param_names.add(key)
            deduped.append(entry)
        cloudfront_access_by_service[service_name] = sorted(
            deduped, key=lambda item: item["env_key"]
        )

    for svc in config.services:
        has_alb_target = svc.port is not None and svc.name in routed_alb_target_services
        name_pascal = _pascalize(svc.name)
        secret_params: list[dict[str, object]] = []
        service_has_rds_secret = False
        for sec_name in svc.secrets:
            secret_cfg = secrets_by_name.get(sec_name)
            source = _enum_value(secret_cfg.source) if secret_cfg else "generate"
            rds_key = None
            if source == "rds":
                rds_key = _normalize_rds_json_key(
                    str(secret_cfg.existing_secret_name).strip()
                    if secret_cfg and secret_cfg.existing_secret_name
                    else rds_secret_key_by_env.get(sec_name)
                )
            if source == "rds":
                service_has_rds_secret = True
            secret_params.append(
                {
                    "secret_name": sec_name,
                    "param_name": f"SecretArn{_pascalize(sec_name)}",
                    "source": source,
                    "requires_param": source != "rds",
                    "rds_json_key": rds_key,
                }
            )

        if config.rds and svc.name in rds_expose_to:
            present_secret_names = {
                str(param["secret_name"]) for param in secret_params
            }
            for sec_name in required_postgres_secret_names:
                if sec_name in present_secret_names:
                    continue
                secret_params.append(
                    {
                        "secret_name": sec_name,
                        "param_name": f"SecretArn{_pascalize(sec_name)}",
                        "source": "rds",
                        "requires_param": False,
                        "rds_json_key": rds_secret_key_by_env[sec_name],
                    }
                )

        if has_alb_target:
            alb_target_services[svc.name] = {
                "stack_logical_id": f"Service{name_pascal}",
                "target_group_output": "TargetGroupArn",
            }
        services_ctx.append(
            {
                "name": svc.name,
                "name_pascal": name_pascal,
                "svc": svc,
                "has_alb_target": has_alb_target,
                "launch_type": _enum_value(svc.launch_type),
                "architecture": _enum_value(svc.architecture)
                if svc.architecture is not None
                else None,
                "user_data_script_content": _resolve_user_data_script_content(
                    svc.user_data_script_content,
                    svc.user_data_script,
                ),
                "has_rds": bool(config.rds)
                and (svc.name in rds_expose_to or service_has_rds_secret),
                "s3_vars": s3_access_by_service.get(svc.name, []),
                "cloudfront_vars": cloudfront_access_by_service.get(svc.name, []),
                "secret_params": secret_params,
                "ebs_params": [
                    {
                        "name": v.name,
                        "name_pascal": _pascalize(v.name),
                        "size_gb": v.size_gb,
                        "mount_path": v.mount_path,
                        "device_name": v.device_name,
                        "filesystem_type": v.filesystem_type,
                        "volume_type": v.volume_type,
                    }
                    for v in svc.ebs_volumes
                ],
            }
        )

    path_rules_by_service: dict[str, list[dict[str, object]]] = {}
    for rule in config.alb.path_rules:
        target_ctx = alb_target_services.get(rule.target_service)
        if not target_ctx:
            continue
        path_rules_by_service.setdefault(rule.target_service, []).append(
            {
                "name": rule.name,
                "name_pascal": _pascalize(rule.name),
                "path_pattern": rule.path_pattern,
                "priority": rule.priority,
            }
        )
    for svc_ctx in services_ctx:
        svc_name = str(svc_ctx["name"])
        svc_path_rules = path_rules_by_service.get(svc_name, [])
        is_default_listener_target = bool(
            config.alb.domain
            and config.alb.default_target_service == svc_name
            and svc_ctx["has_alb_target"]
        )
        listener_hostnames: list[dict[str, object]] = []
        if config.alb.domain:
            listener_hostnames.append({"is_ref": True, "ref_name": "ClusterDomain"})
            cf_custom_domain = (config.cloudfront.custom_domain or "").strip()
            if cf_custom_domain and cf_custom_domain != config.alb.domain:
                listener_hostnames.append({"is_ref": False, "value": cf_custom_domain})

        svc_ctx["default_listener_priority"] = config.alb.default_listener_priority
        svc_ctx["is_default_listener_target"] = is_default_listener_target
        svc_ctx["service_path_rules"] = svc_path_rules
        svc_ctx["listener_hostnames"] = listener_hostnames
        svc_ctx["has_cluster_routing_rules"] = bool(
            config.alb.domain and (is_default_listener_target or svc_path_rules)
        )

    return {
        "project_name": config.project_name,
        "project_name_pascal": _pascalize(config.project_name),
        "aws_region": config.aws_region,
        "vpc_name": config.vpc_name,
        "vpc_id": config.vpc_id,
        "private_subnet_ids": config.private_subnet_ids,
        "public_subnet_ids": config.public_subnet_ids,
        "services": config.services,
        "services_ctx": services_ctx,
        "environments": config.environments,
        "has_rds": config.rds is not None,
        "has_s3": len(config.s3_buckets) > 0,
        "has_cloudfront": any(
            b.cloudfront and b.mode.value != "existing" for b in config.s3_buckets
        ),
        "has_alb_cloudfront": config.cloudfront.enabled,
        "alb_cloudfront": {
            "origin_https_only": config.cloudfront.origin_https_only,
            "custom_domain": config.cloudfront.custom_domain,
            "certificate_arn": config.cloudfront.certificate_arn,
            "price_class": config.cloudfront.price_class,
            "comment": config.cloudfront.comment,
            "cached_behaviors": [
                {
                    "name": behavior.name,
                    "name_pascal": _pascalize(behavior.name),
                    "path_pattern": behavior.path_pattern,
                    "compress": behavior.compress,
                    "cache_by_origin_headers": behavior.cache_by_origin_headers,
                    "min_ttl_seconds": behavior.min_ttl_seconds,
                    "default_ttl_seconds": behavior.default_ttl_seconds,
                    "max_ttl_seconds": behavior.max_ttl_seconds,
                    "query_strings": _enum_value(behavior.query_strings),
                    "query_string_allowlist": behavior.query_string_allowlist,
                    "cookies": _enum_value(behavior.cookies),
                    "cookie_allowlist": behavior.cookie_allowlist,
                    "forward_authorization_header": behavior.forward_authorization_header,
                }
                for behavior in config.cloudfront.cached_behaviors
            ],
        },
        "has_ec2": any(_enum_value(s.launch_type) == "ec2" for s in config.services),
        "has_service_discovery": any(
            s.enable_service_discovery for s in config.services
        ),
        "rds": config.rds,
        "rds_master_username": (
            _derive_rds_master_username(config.rds.database_name)
            if config.rds is not None
            else ""
        ),
        "s3_buckets": config.s3_buckets,
        "alb": config.alb,
        "secrets": config.secrets,
        "tags": config.tags,
    }


def _render(
    env: Environment,
    template_name: str,
    output_path: Path,
    ctx: dict,
) -> None:
    """Render a single template to a file."""
    template = env.get_template(template_name)
    content = template.render(**ctx)
    output_path.write_text(content)
