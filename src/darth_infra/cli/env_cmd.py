"""``darth-infra env`` — dump all secrets to a .env file."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import boto3
import click

from .helpers import console, require_config
from .secret_cmd import _extract_secret_value, _resolve_secret_id
from .version_floor import bump_cli_version_floor


@click.command("env")
@click.option("--env", "env_name", required=True, help="Environment name.")
@click.option(
    "--file",
    "env_file",
    default=".env",
    show_default=True,
    help="Path to the .env file to append secrets to.",
)
def env_cmd(env_name: str, env_file: str) -> None:
    """Retrieve all config secrets and append them to a .env file."""
    config, project_root = require_config()

    if not config.secrets:
        console.print("[yellow]No secrets defined in config.[/yellow]")
        return

    sm = boto3.client("secretsmanager", region_name=config.aws_region)

    entries: list[str] = []
    for secret_cfg in config.secrets:
        try:
            secret_id = _resolve_secret_id(config, env_name, secret_cfg.name)
            resp = sm.get_secret_value(SecretId=secret_id)
            value = _extract_secret_value(resp)
            entries.append(f"{secret_cfg.name}={value}")
        except Exception as exc:
            console.print(
                f"[red]Failed to retrieve secret '{secret_cfg.name}': {exc}[/red]"
            )
            raise SystemExit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    block = f"\n# Secrets retrieved on {timestamp}\n" + "\n".join(entries) + "\n"

    dest = Path(env_file)
    with dest.open("a") as fh:
        fh.write(block)

    bump_cli_version_floor(project_root)
    console.print(f"[green]Appended {len(entries)} secret(s) to {dest}[/green]")
