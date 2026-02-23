"""darth-infra CLI — main entry point."""

import click

from .init_cmd import init_cmd
from .deploy_cmd import deploy
from .build_cmd import build
from .push_cmd import push
from .logs_cmd import logs
from .exec_cmd import exec_cmd
from .secret_cmd import secret_cmd
from .destroy_cmd import destroy
from .status_cmd import status
from .render_cmd import render_cmd


@click.group()
@click.version_option(package_name="darth-infra")
def cli() -> None:
    """darth-infra — Deploy websites to AWS ECS with multi-environment support."""


cli.add_command(init_cmd, name="init")
cli.add_command(deploy)
cli.add_command(build)
cli.add_command(push)
cli.add_command(logs)
cli.add_command(exec_cmd, name="exec")
cli.add_command(secret_cmd)
cli.add_command(destroy)
cli.add_command(status)
cli.add_command(render_cmd)


if __name__ == "__main__":
    cli()
