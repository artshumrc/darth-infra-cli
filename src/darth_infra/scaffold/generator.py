"""Scaffold generator - renders CloudFormation templates into a project directory."""

from __future__ import annotations

from dataclasses import asdict
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..config.models import ProjectConfig
from .context import derive_render_context

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "cfn"


def generate_project(
    config: ProjectConfig,
    output_dir: Path,
    *,
    write_config: bool = True,
) -> Path:
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
    if write_config:
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
    """Adapt the typed context to the mapping expected by the Jinja pipeline."""
    return asdict(derive_render_context(config))


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
