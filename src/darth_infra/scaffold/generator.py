"""Scaffold generator - renders a CloudFormation project into a directory.

CFN templates are built as troposphere object trees (see
:mod:`darth_infra.scaffold.builders`) and serialized to YAML. Only the prose
``README.md`` remains Jinja-templated.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..config.models import ProjectConfig
from .builders import build_project_templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "cfn"


_OVERRIDES_PLACEHOLDER = """AWSTemplateFormatVersion: '2010-09-09'
Description: User-managed CloudFormation overrides for {project_name}

Resources:
  # Placeholder so this nested stack is valid before custom resources are added.
  NoopHandle:
    Type: AWS::CloudFormation::WaitConditionHandle

Outputs: {{}}
"""


def _render_overrides_placeholder(config: ProjectConfig) -> str:
    """Return the static user-overrides nested-stack placeholder content."""
    return _OVERRIDES_PLACEHOLDER.format(project_name=config.project_name)


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

    # Prose (README) is not part of the troposphere migration and stays Jinja.
    jinja_env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    readme = jinja_env.get_template("README.md.j2")
    (output_dir / "README.md").write_text(
        readme.render(project_name=config.project_name)
    )

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

    # Build → serialize → write. Output paths are the frozen public contract.
    templates = build_project_templates(config)
    for relative_path, template in templates.items():
        output_path = output_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(template.to_yaml())

    # Do not overwrite user-owned custom overrides template once created.
    custom_overrides = custom_dir / "overrides.yaml"
    if not custom_overrides.exists():
        custom_overrides.write_text(_render_overrides_placeholder(config))

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
