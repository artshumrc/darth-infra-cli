"""``darth-infra secret`` — retrieve and print a secret value."""

from __future__ import annotations

import base64

import boto3
import click

from ..config.models import ProjectConfig
from .helpers import console, require_config


@click.command("secret")
@click.argument("secret")
@click.option("--env", "env_name", required=True, help="Environment name.")
@click.option(
    "--json-key",
    default=None,
    help="Optional JSON key to extract from a JSON-formatted secret string.",
)
def secret_cmd(secret: str, env_name: str, json_key: str | None) -> None:
    """Retrieve a secret value from AWS Secrets Manager and print it."""
    config, _ = require_config()

    sm = boto3.client("secretsmanager", region_name=config.aws_region)

    try:
        secret_id = _resolve_secret_id(config, env_name, secret)
        resp = sm.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        console.print(f"[red]Failed to retrieve secret '{secret}': {exc}[/red]")
        raise SystemExit(1)

    value = _extract_secret_value(resp)

    if json_key:
        try:
            import json

            parsed = json.loads(value)
            if not isinstance(parsed, dict) or json_key not in parsed:
                raise KeyError(json_key)
            value = str(parsed[json_key])
        except Exception:
            console.print(
                f"[red]Could not extract json key '{json_key}' from secret value[/red]"
            )
            raise SystemExit(1)

    # Use plain stdout so command substitution works cleanly.
    click.echo(value)


def _resolve_secret_id(config: ProjectConfig, env_name: str, secret: str) -> str:
    cfg_secret = next((s for s in config.secrets if s.name == secret), None)
    if cfg_secret is None:
        return secret

    if cfg_secret.source.value == "generate":
        return f"{config.project_name}-{env_name}-{secret.lower().replace('_', '-')}"

    if cfg_secret.source.value == "env":
        stack_name = f"{config.project_name}-ecs-{env_name}"
        param_key = f"EnvSecretArn{secret.replace('_', '').replace('-', '')}"

        cf = boto3.client("cloudformation", region_name=config.aws_region)
        stacks = cf.describe_stacks(StackName=stack_name).get("Stacks", [])
        if not stacks:
            raise RuntimeError(f"Stack '{stack_name}' not found")

        for param in stacks[0].get("Parameters", []):
            if param.get("ParameterKey") == param_key:
                value = (param.get("ParameterValue") or "").strip()
                if value:
                    return value

        raise RuntimeError(
            f"Could not resolve secret ARN from stack parameter '{param_key}'"
        )

    return secret


def _extract_secret_value(resp: dict) -> str:
    if "SecretString" in resp and resp["SecretString"] is not None:
        return str(resp["SecretString"])

    binary_val = resp.get("SecretBinary")
    if binary_val is None:
        return ""

    if isinstance(binary_val, (bytes, bytearray)):
        raw = bytes(binary_val)
    else:
        raw = base64.b64decode(binary_val)

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode("ascii")
