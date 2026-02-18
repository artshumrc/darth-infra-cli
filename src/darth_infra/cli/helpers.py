"""Shared CLI helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import boto3
from rich.console import Console

from ..config.loader import find_config, load_config
from ..config.models import ProjectConfig

console = Console()


def require_config() -> tuple[ProjectConfig, Path]:
    """Load config or exit with an error."""
    try:
        config_path = find_config()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    config = load_config(config_path)
    return config, config_path.parent


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


def run_cdk(args: list[str], project_dir: Path) -> int:
    """Run a CDK command inside the project directory."""
    cmd = ["uv", "run", "cdk", *args]
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, cwd=str(project_dir))
    return result.returncode


def get_cluster_name(project_name: str, env: str) -> str:
    return f"{project_name}-{env}"


def get_service_name(project_name: str, env: str, service: str) -> str:
    return f"{project_name}-{env}-{service}"
