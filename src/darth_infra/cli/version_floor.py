"""CLI version floor helpers."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import click
from packaging.version import Version

from ..config.loader import CONFIG_FILENAME, dump_config, load_config
from ..config.models import ProjectConfig


def get_current_cli_version() -> Version:
    return Version(get_current_cli_version_string())


def get_current_cli_version_string() -> str:
    return version("darth-infra")


def enforce_cli_version_floor(config: ProjectConfig) -> None:
    if not config.cli_version_floor:
        return

    floor = Version(config.cli_version_floor)
    current = get_current_cli_version()
    if current < floor:
        raise click.ClickException(
            "This project requires darth-infra CLI "
            f">= {floor}; current version is {current}. Upgrade darth-infra and retry."
        )


def apply_current_cli_version_floor(config: ProjectConfig) -> bool:
    current = get_current_cli_version()
    if config.cli_version_floor and Version(config.cli_version_floor) >= current:
        return False

    config.cli_version_floor = get_current_cli_version_string()
    return True


def bump_cli_version_floor(project_dir: Path) -> None:
    config_path = project_dir / CONFIG_FILENAME
    config = load_config(config_path)
    if not apply_current_cli_version_floor(config):
        return
    config_path.write_text(dump_config(config))
