"""Smoke tests at the ``generate_project`` I/O seam.

These assert file-writing behavior only (frozen output paths, valid YAML,
cfn-lint validity, write-once custom overrides). Template *structure* is
covered by the builder tests; nothing here asserts on rendered CFN text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from cfn_flip import load_yaml

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    S3BucketConnection,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.generator import generate_project


def _featured_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(name="web", port=8000, secrets=["APP_SECRET"]),
            ServiceConfig(name="worker", port=None),
        ],
        secrets=[SecretConfig(name="APP_SECRET", source=SecretSource.GENERATE)],
        alb=AlbConfig(
            mode=AlbMode.DEDICATED,
            certificate_arn=(
                "arn:aws:acm:us-east-1:123456789012:certificate/"
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            ),
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
        ),
        rds=RdsConfig(database_name="demo", expose_to=["web"]),
        s3_buckets=[
            S3BucketConfig(
                name="media",
                connections=[S3BucketConnection(service="web", env_key="MEDIA")],
            )
        ],
    )


def _cfn_lint(path: Path) -> None:
    result = subprocess.run(
        ["cfn-lint", "--non-zero-exit-code", "error", "--template", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generate_project_writes_frozen_paths(tmp_path: Path) -> None:
    output_dir = generate_project(_featured_config(), tmp_path / "out")

    expected = [
        output_dir / "README.md",
        output_dir / "darth-infra.toml",
        output_dir / "templates" / "generated" / "root.yaml",
        output_dir / "templates" / "generated" / "services" / "web.yaml",
        output_dir / "templates" / "generated" / "services" / "worker.yaml",
        output_dir / "templates" / "custom" / "overrides.yaml",
    ]
    for path in expected:
        assert path.is_file(), f"missing generated file: {path}"


def test_generated_templates_parse_as_yaml_and_pass_cfn_lint(tmp_path: Path) -> None:
    output_dir = generate_project(_featured_config(), tmp_path / "out")
    generated = output_dir / "templates" / "generated"

    template_paths = [
        generated / "root.yaml",
        generated / "services" / "web.yaml",
        generated / "services" / "worker.yaml",
        output_dir / "templates" / "custom" / "overrides.yaml",
    ]
    for path in template_paths:
        parsed = load_yaml(path.read_text())
        assert parsed["Resources"]
        _cfn_lint(path)


def test_generate_project_does_not_overwrite_existing_custom_overrides(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    custom_overrides = output_dir / "templates" / "custom" / "overrides.yaml"
    custom_overrides.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "# hand-edited custom overrides — must survive regeneration\n"
    custom_overrides.write_text(sentinel)

    generate_project(_featured_config(), output_dir)

    assert custom_overrides.read_text() == sentinel


def test_generate_project_writes_overrides_placeholder_when_absent(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(_featured_config(), tmp_path / "out")
    custom_overrides = (
        output_dir / "templates" / "custom" / "overrides.yaml"
    ).read_text()

    assert "User-managed CloudFormation overrides for demo" in custom_overrides
    assert "AWS::CloudFormation::WaitConditionHandle" in custom_overrides
