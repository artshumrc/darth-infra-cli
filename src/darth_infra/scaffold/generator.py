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


def _resolve_user_data_script_content(inline: str | None, path: str | None) -> str | None:
    content = (inline or "").strip()
    if not content and path:
        src_script = Path.cwd() / path
        if src_script.is_file():
            content = src_script.read_text().strip()
    if not content:
        return None
    # Escape Fn::Sub interpolation markers from user-provided script content.
    return content.replace("${", "$${")


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
    rds_expose_to = set(config.rds.expose_to if config.rds else [])

    for svc in config.services:
        has_alb_target = svc.port is not None
        name_pascal = _pascalize(svc.name)
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
                "has_rds": svc.name in rds_expose_to,
                "s3_vars": [
                    {
                        "bucket_name": b,
                        "env_key": f"S3_BUCKET_{b.upper().replace('-', '_')}",
                        "param_name": f"BucketName{_pascalize(b)}",
                        "arn_param_name": f"BucketArn{_pascalize(b)}",
                    }
                    for b in svc.s3_access
                ],
                "secret_params": [
                    {
                        "secret_name": sec,
                        "param_name": f"SecretArn{_pascalize(sec)}",
                    }
                    for sec in svc.secrets
                ],
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
        svc_ctx["cluster_domain"] = config.alb.domain or ""
        svc_ctx["default_listener_priority"] = config.alb.default_listener_priority
        svc_ctx["is_default_listener_target"] = is_default_listener_target
        svc_ctx["service_path_rules"] = svc_path_rules
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
        "has_cloudfront": any(b.cloudfront for b in config.s3_buckets),
        "has_ec2": any(_enum_value(s.launch_type) == "ec2" for s in config.services),
        "has_service_discovery": any(
            s.enable_service_discovery for s in config.services
        ),
        "rds": config.rds,
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
