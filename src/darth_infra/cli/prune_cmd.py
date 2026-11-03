"""``darth-infra prune-previews`` — destroy preview environments left idle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import click

from .cfn import idle_previews
from .destroy_cmd import destroy_environment
from .helpers import console, require_config, resolve_environment_config
from .version_floor import bump_cli_version_floor


@click.command("prune-previews")
@click.option(
    "--idle-days",
    type=click.IntRange(min=1),
    default=7,
    show_default=True,
    help="Destroy previews with no deploy or image push in this many days.",
)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def prune_previews(idle_days: int, force: bool) -> None:
    """Destroy preview environments idle for longer than --idle-days."""
    loaded_config, project_dir = require_config()
    preview = loaded_config.preview_environments
    if not preview.enabled:
        console.print(
            "[red]Preview environments are not enabled in darth-infra.toml.[/red]"
        )
        raise SystemExit(1)

    now = datetime.now(UTC)
    idle = idle_previews(loaded_config, now - timedelta(days=idle_days))
    if not idle:
        console.print(f"[green]No previews idle for {idle_days}+ days.[/green]")
        return

    env_names = sorted(idle)
    for env_name in env_names:
        console.print(f"  {env_name}: idle {(now - idle[env_name]).days} days")
    if not force:
        click.confirm(
            f"Destroy {len(env_names)} idle preview environment(s)?", abort=True
        )

    failed = []
    for env_name in env_names:
        config = resolve_environment_config(
            loaded_config, env_name, preview.base_environment
        )
        if destroy_environment(config, env_name) != 0:
            failed.append(env_name)
    if failed:
        console.print(f"[red]Could not destroy: {', '.join(failed)}[/red]")
        raise SystemExit(1)
    bump_cli_version_floor(project_dir)
