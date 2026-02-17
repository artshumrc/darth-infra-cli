"""Scaffold generator — renders Jinja2 templates into a CDK project directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..config.models import ProjectConfig, LaunchType

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def generate_project(config: ProjectConfig, output_dir: Path) -> Path:
    """Render the full CDK project into *output_dir*.

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

    # Template context
    ctx = _build_context(config)

    # Render top-level files
    _render(jinja_env, "app.py.j2", output_dir / "app.py", ctx)
    _render(jinja_env, "cdk.json.j2", output_dir / "cdk.json", ctx)
    _render(jinja_env, "pyproject.toml.j2", output_dir / "pyproject.toml", ctx)
    _render(jinja_env, "README.md.j2", output_dir / "README.md", ctx)

    # Write darth-infra.toml (the source of truth config)
    from ..config.loader import dump_config

    toml_path = output_dir / "darth-infra.toml"
    toml_path.write_text(dump_config(config))

    # Copy the JSON schema for editor support
    schema_src = Path(__file__).resolve().parent.parent / "darth-infra.schema.json"
    if schema_src.exists():
        shutil.copy2(schema_src, output_dir / "darth-infra.schema.json")

    # Render stacks
    stacks_dir = output_dir / "stacks"
    stacks_dir.mkdir(exist_ok=True)
    constructs_dir = stacks_dir / "constructs"
    constructs_dir.mkdir(exist_ok=True)

    _render(
        jinja_env,
        "stacks/__init__.py.j2",
        stacks_dir / "__init__.py",
        ctx,
    )
    _render(
        jinja_env,
        "stacks/main_stack.py.j2",
        stacks_dir / "main_stack.py",
        ctx,
    )
    _render(
        jinja_env,
        "stacks/constructs/__init__.py.j2",
        constructs_dir / "__init__.py",
        ctx,
    )

    # Always-present constructs
    _render_construct(jinja_env, constructs_dir, "ecr_repository.py", ctx)
    _render_construct(jinja_env, constructs_dir, "ecs_service.py", ctx)
    _render_construct(jinja_env, constructs_dir, "alb.py", ctx)
    _render_construct(jinja_env, constructs_dir, "secrets.py", ctx)

    # Optional constructs
    if config.rds:
        _render_construct(jinja_env, constructs_dir, "rds_database.py", ctx)
    if config.s3_buckets:
        _render_construct(jinja_env, constructs_dir, "s3_bucket.py", ctx)
    if any(b.cloudfront for b in config.s3_buckets):
        _render_construct(jinja_env, constructs_dir, "cloudfront_distribution.py", ctx)

    # Copy user data scripts for EC2 services
    for svc in config.services:
        if svc.user_data_script:
            src_script = Path.cwd() / svc.user_data_script
            if src_script.is_file():
                dest_script = output_dir / svc.user_data_script
                dest_script.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_script, dest_script)

    return output_dir


def _build_context(config: ProjectConfig) -> dict:
    """Build a Jinja2 template context from a ProjectConfig."""
    return {
        "project_name": config.project_name,
        "aws_region": config.aws_region,
        "vpc_name": config.vpc_name,
        "services": config.services,
        "environments": config.environments,
        "has_rds": config.rds is not None,
        "has_s3": len(config.s3_buckets) > 0,
        "has_cloudfront": any(b.cloudfront for b in config.s3_buckets),
        "has_ec2": any(s.launch_type == LaunchType.EC2 for s in config.services),
        "has_ebs": any(s.ebs_volumes for s in config.services),
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


def _render_construct(
    env: Environment,
    constructs_dir: Path,
    filename: str,
    ctx: dict,
) -> None:
    """Render a construct template."""
    _render(
        env,
        f"stacks/constructs/{filename}.j2",
        constructs_dir / filename,
        ctx,
    )
