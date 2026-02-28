"""Shared Docker/ECR operations for build, push, and deploy flows."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import boto3
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..config.models import ProjectConfig, ServiceConfig
from .helpers import console


def select_services(
    config: ProjectConfig,
    service_name: str | None,
) -> list[ServiceConfig]:
    """Return selected services or exit if the requested service is missing."""
    services = config.services
    if service_name:
        services = [service for service in services if service.name == service_name]
        if not services:
            console.print(
                f"[red]Service '{service_name}' not found. "
                f"Available: {', '.join(s.name for s in config.services)}[/red]"
            )
            raise SystemExit(1)
    return services


def select_internal_services(
    config: ProjectConfig,
    service_name: str | None,
) -> list[ServiceConfig]:
    """Return selected services that are built/pushed internally."""
    services = select_services(config, service_name)
    return [service for service in services if not service.image]


def build_images(
    config: ProjectConfig,
    project_dir: Path,
    service_name: str | None,
) -> None:
    """Build local Docker images for internal services."""
    ensure_docker_buildx()
    services = select_services(config, service_name)

    status_by_service: dict[str, str] = {service.name: "queued" for service in services}
    last_update = "Starting build flow"
    failed_code: int | None = None
    failed_message = ""

    with Live(console=console, refresh_per_second=8, transient=False) as live:
        for service in services:
            if service.image:
                status_by_service[service.name] = "skipped (external image)"
                last_update = f"Skipped {service.name}: uses external image"
                live.update(
                    _render_docker_live_view(
                        title="Docker Build",
                        summary_rows=[
                            ("Phase", "Building internal service images", "cyan"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "dim"),
                        ],
                        service_status=status_by_service,
                    )
                )
                continue

            tag = local_image_tag(config.project_name, service.name)
            cmd = [
                "docker",
                "buildx",
                "build",
                "--load",
                "-t",
                tag,
                "-f",
                service.dockerfile,
            ]
            if service.docker_build_target:
                cmd.extend(["--target", service.docker_build_target])
            cmd.append(service.build_context)

            status_by_service[service.name] = "building"
            last_update = f"Building {service.name}"
            live.update(
                _render_docker_live_view(
                    title="Docker Build",
                    summary_rows=[
                        ("Phase", "Building internal service images", "cyan"),
                        ("Current service", service.name, "cyan"),
                        ("Last update", last_update, "white"),
                    ],
                    service_status=status_by_service,
                )
            )

            result = _run_quiet(cmd, cwd=project_dir)
            if result.returncode != 0:
                status_by_service[service.name] = f"failed (exit {result.returncode})"
                failed_code = result.returncode
                failed_message = _tail_stderr(result.stderr)
                last_update = f"Build failed for {service.name}"
                live.update(
                    _render_docker_live_view(
                        title="Docker Build",
                        summary_rows=[
                            ("Phase", "Building internal service images", "cyan"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "red"),
                            (
                                "Error",
                                failed_message
                                if failed_message
                                else "No error details captured",
                                "red",
                            ),
                        ],
                        service_status=status_by_service,
                    )
                )
                break

            status_by_service[service.name] = f"built ({tag})"
            last_update = f"Built {service.name}"
            live.update(
                _render_docker_live_view(
                    title="Docker Build",
                    summary_rows=[
                        ("Phase", "Building internal service images", "cyan"),
                        ("Current service", service.name, "cyan"),
                        ("Last update", last_update, "green"),
                    ],
                    service_status=status_by_service,
                )
            )

    if failed_code is not None:
        console.print(f"[red]Build failed with exit code {failed_code}[/red]")
        if failed_message:
            console.print(f"[red]{failed_message}[/red]")
        raise SystemExit(failed_code)

    console.print("[green]✓ Docker build completed[/green]")


def push_images(
    config: ProjectConfig,
    env_name: str,
    service_name: str | None,
) -> None:
    """Tag and push local Docker images to ECR with latest + immutable tags."""
    services = select_services(config, service_name)
    account = boto3.client("sts").get_caller_identity()["Account"]
    registry = ecr_registry_uri(account, config.aws_region)

    login_cmd = (
        f"aws ecr get-login-password --region {config.aws_region} "
        f"| docker login --username AWS --password-stdin {registry}"
    )
    status_by_service: dict[str, str] = {service.name: "queued" for service in services}
    last_update = "Logging in to ECR"
    failed_code: int | None = None
    failed_message = ""
    immutable_tag = build_immutable_tag()

    with Live(console=console, refresh_per_second=8, transient=False) as live:
        live.update(
            _render_docker_live_view(
                title="Docker Push",
                summary_rows=[
                    ("Phase", "ECR authentication", "cyan"),
                    ("Registry", registry, "white"),
                    ("Last update", last_update, "white"),
                ],
                service_status=status_by_service,
            )
        )

        login_result = _run_quiet(login_cmd, shell=True)
        if login_result.returncode != 0:
            failed_code = login_result.returncode
            failed_message = _tail_stderr(login_result.stderr)
            live.update(
                _render_docker_live_view(
                    title="Docker Push",
                    summary_rows=[
                        ("Phase", "ECR authentication", "cyan"),
                        ("Registry", registry, "white"),
                        ("Last update", "ECR login failed", "red"),
                        (
                            "Error",
                            failed_message
                            if failed_message
                            else "No error details captured",
                            "red",
                        ),
                    ],
                    service_status=status_by_service,
                )
            )
        else:
            last_update = "ECR login succeeded"
            live.update(
                _render_docker_live_view(
                    title="Docker Push",
                    summary_rows=[
                        ("Phase", "Pushing service images", "cyan"),
                        ("Registry", registry, "white"),
                        ("Immutable tag", immutable_tag, "white"),
                        ("Last update", last_update, "green"),
                    ],
                    service_status=status_by_service,
                )
            )

        if failed_code is None:
            for service in services:
                if service.image:
                    status_by_service[service.name] = "skipped (external image)"
                    last_update = f"Skipped {service.name}: uses external image"
                    live.update(
                        _render_docker_live_view(
                            title="Docker Push",
                            summary_rows=[
                                ("Phase", "Pushing service images", "cyan"),
                                ("Registry", registry, "white"),
                                ("Immutable tag", immutable_tag, "white"),
                                ("Last update", last_update, "dim"),
                            ],
                            service_status=status_by_service,
                        )
                    )
                    continue

                local_tag = local_image_tag(config.project_name, service.name)
                repo = ecr_repo_name(config.project_name, env_name, service.name)
                latest_remote_tag = f"{registry}/{repo}:latest"
                immutable_remote_tag = f"{registry}/{repo}:{immutable_tag}"

                status_by_service[service.name] = "tagging immutable"
                last_update = f"Tagging {service.name} for immutable push"
                live.update(
                    _render_docker_live_view(
                        title="Docker Push",
                        summary_rows=[
                            ("Phase", "Pushing service images", "cyan"),
                            ("Registry", registry, "white"),
                            ("Immutable tag", immutable_tag, "white"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "white"),
                        ],
                        service_status=status_by_service,
                    )
                )

                tag_immutable_result = _run_quiet(
                    ["docker", "tag", local_tag, immutable_remote_tag]
                )
                if tag_immutable_result.returncode != 0:
                    status_by_service[service.name] = (
                        f"failed tagging immutable (exit {tag_immutable_result.returncode})"
                    )
                    failed_code = tag_immutable_result.returncode
                    failed_message = _tail_stderr(tag_immutable_result.stderr)
                    live.update(
                        _render_docker_live_view(
                            title="Docker Push",
                            summary_rows=[
                                ("Phase", "Pushing service images", "cyan"),
                                ("Registry", registry, "white"),
                                ("Current service", service.name, "cyan"),
                                (
                                    "Last update",
                                    "Failed while tagging immutable image",
                                    "red",
                                ),
                                (
                                    "Error",
                                    failed_message
                                    if failed_message
                                    else "No error details captured",
                                    "red",
                                ),
                            ],
                            service_status=status_by_service,
                        )
                    )
                    break

                status_by_service[service.name] = "pushing immutable"
                last_update = f"Pushing immutable image for {service.name}"
                live.update(
                    _render_docker_live_view(
                        title="Docker Push",
                        summary_rows=[
                            ("Phase", "Pushing service images", "cyan"),
                            ("Registry", registry, "white"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "white"),
                        ],
                        service_status=status_by_service,
                    )
                )

                push_immutable_result = _run_quiet(
                    ["docker", "push", immutable_remote_tag]
                )
                if push_immutable_result.returncode != 0:
                    status_by_service[service.name] = (
                        f"failed pushing immutable (exit {push_immutable_result.returncode})"
                    )
                    failed_code = push_immutable_result.returncode
                    failed_message = _tail_stderr(push_immutable_result.stderr)
                    live.update(
                        _render_docker_live_view(
                            title="Docker Push",
                            summary_rows=[
                                ("Phase", "Pushing service images", "cyan"),
                                ("Registry", registry, "white"),
                                ("Current service", service.name, "cyan"),
                                ("Last update", "Immutable push failed", "red"),
                                (
                                    "Error",
                                    failed_message
                                    if failed_message
                                    else "No error details captured",
                                    "red",
                                ),
                            ],
                            service_status=status_by_service,
                        )
                    )
                    break

                status_by_service[service.name] = "tagging latest"
                last_update = f"Tagging latest image for {service.name}"
                live.update(
                    _render_docker_live_view(
                        title="Docker Push",
                        summary_rows=[
                            ("Phase", "Pushing service images", "cyan"),
                            ("Registry", registry, "white"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "white"),
                        ],
                        service_status=status_by_service,
                    )
                )

                tag_latest_result = _run_quiet(
                    ["docker", "tag", immutable_remote_tag, latest_remote_tag]
                )
                if tag_latest_result.returncode != 0:
                    status_by_service[service.name] = (
                        f"failed tagging latest (exit {tag_latest_result.returncode})"
                    )
                    failed_code = tag_latest_result.returncode
                    failed_message = _tail_stderr(tag_latest_result.stderr)
                    live.update(
                        _render_docker_live_view(
                            title="Docker Push",
                            summary_rows=[
                                ("Phase", "Pushing service images", "cyan"),
                                ("Registry", registry, "white"),
                                ("Current service", service.name, "cyan"),
                                (
                                    "Last update",
                                    "Failed while tagging latest image",
                                    "red",
                                ),
                                (
                                    "Error",
                                    failed_message
                                    if failed_message
                                    else "No error details captured",
                                    "red",
                                ),
                            ],
                            service_status=status_by_service,
                        )
                    )
                    break

                status_by_service[service.name] = "pushing latest"
                last_update = f"Pushing latest image for {service.name}"
                live.update(
                    _render_docker_live_view(
                        title="Docker Push",
                        summary_rows=[
                            ("Phase", "Pushing service images", "cyan"),
                            ("Registry", registry, "white"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "white"),
                        ],
                        service_status=status_by_service,
                    )
                )

                push_latest_result = _run_quiet(["docker", "push", latest_remote_tag])
                if push_latest_result.returncode != 0:
                    status_by_service[service.name] = (
                        f"failed pushing latest (exit {push_latest_result.returncode})"
                    )
                    failed_code = push_latest_result.returncode
                    failed_message = _tail_stderr(push_latest_result.stderr)
                    live.update(
                        _render_docker_live_view(
                            title="Docker Push",
                            summary_rows=[
                                ("Phase", "Pushing service images", "cyan"),
                                ("Registry", registry, "white"),
                                ("Current service", service.name, "cyan"),
                                ("Last update", "Latest push failed", "red"),
                                (
                                    "Error",
                                    failed_message
                                    if failed_message
                                    else "No error details captured",
                                    "red",
                                ),
                            ],
                            service_status=status_by_service,
                        )
                    )
                    break

                status_by_service[service.name] = "pushed latest + immutable"
                last_update = f"Pushed {service.name}"
                live.update(
                    _render_docker_live_view(
                        title="Docker Push",
                        summary_rows=[
                            ("Phase", "Pushing service images", "cyan"),
                            ("Registry", registry, "white"),
                            ("Immutable tag", immutable_tag, "white"),
                            ("Current service", service.name, "cyan"),
                            ("Last update", last_update, "green"),
                        ],
                        service_status=status_by_service,
                    )
                )

    if failed_code is not None:
        console.print(f"[red]Push failed with exit code {failed_code}[/red]")
        if failed_message:
            console.print(f"[red]{failed_message}[/red]")
        raise SystemExit(failed_code)

    console.print("[green]✓ Docker push completed[/green]")


def local_image_tag(project_name: str, service_name: str) -> str:
    return f"{project_name}-{service_name}:latest"


def ecr_registry_uri(account_id: str, region: str) -> str:
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com"


def ecr_repo_name(project_name: str, env_name: str, service_name: str) -> str:
    return f"{project_name}/{env_name}/{service_name}"


def build_immutable_tag() -> str:
    return datetime.now(UTC).strftime("build-%Y%m%d%H%M%S")


def ensure_docker_buildx() -> None:
    """Exit with guidance when Docker buildx is not installed/available."""
    result = subprocess.run(
        ["docker", "buildx", "version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return

    console.print("[red]Docker buildx is required for image builds.[/red]")
    console.print(
        "[yellow]Install/enable Docker buildx to use BuildKit:[/yellow] "
        "[blue]https://docs.docker.com/go/buildx/[/blue]"
    )
    raise SystemExit(1)


def _run_quiet(
    cmd: list[str] | str,
    *,
    cwd: Path | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        shell=shell,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _tail_stderr(stderr: str | None, *, max_lines: int = 5) -> str:
    if not stderr:
        return ""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return " | ".join(lines[-max_lines:])


def _status_style(value: str) -> str:
    lowered = value.lower()
    if "failed" in lowered:
        return "red"
    if "pushed" in lowered or "built" in lowered:
        return "green"
    if "skipped" in lowered:
        return "dim"
    if "building" in lowered or "pushing" in lowered or "tagging" in lowered:
        return "yellow"
    return "white"


def _render_docker_live_view(
    *,
    title: str,
    summary_rows: list[tuple[str, str, str]],
    service_status: dict[str, str],
) -> Group:
    summary_table = Table(title="Summary", show_header=False, expand=True)
    summary_table.add_column("Key", style="bold cyan", no_wrap=True, width=18)
    summary_table.add_column("Value", overflow="fold")
    for key, value, style in summary_rows:
        summary_table.add_row(key, f"[{style}]{value}[/{style}]")

    service_table = Table(title="Services", show_header=False, expand=True)
    service_table.add_column("Service", style="bold cyan", no_wrap=True, width=22)
    service_table.add_column("State", overflow="fold")
    for service_name, state in service_status.items():
        style = _status_style(state)
        service_table.add_row(service_name, f"[{style}]{state}[/{style}]")

    return Group(
        Panel(summary_table, border_style="cyan", title=title),
        Panel(service_table, border_style="green"),
    )
