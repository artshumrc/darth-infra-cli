"""Review screen — summary and confirm."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from ...config.models import (
    AlbConfig,
    AlbMode,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)


class ReviewScreen(Screen):
    """Final screen: display project summary and confirm scaffolding."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield Static("Review & Confirm", classes="title")
            with VerticalScroll():
                yield Static(self._build_summary(), id="summary")
            with Vertical(classes="button-row"):
                yield Button("← Back", id="back", variant="default")
                yield Button("Create Project ✓", id="confirm", variant="primary")

    def _build_summary(self) -> str:
        s = self._state
        lines = [
            f"[bold]Project:[/bold] {s['project_name']}",
            f"[bold]Region:[/bold]  {s['aws_region']}",
            f"[bold]VPC:[/bold]     {s['vpc_name']}",
            f"[bold]Envs:[/bold]    {', '.join(s['environments'])}",
            "",
            f"[bold]Services ({len(s['services'])}):[/bold]",
        ]
        for svc in s["services"]:
            port_info = f":{svc['port']}" if svc.get("port") else " (worker)"
            domain_info = f" → {svc['domain']}" if svc.get("domain") else ""
            lines.append(f"  • {svc['name']}{port_info}{domain_info}")

        if s.get("rds"):
            rds = s["rds"]
            lines.append("")
            lines.append(
                f"[bold]RDS:[/bold] {rds['database_name']} ({rds['instance_type']})"
            )
            lines.append(f"  Exposed to: {', '.join(rds['expose_to'])}")

        if s.get("s3_buckets"):
            lines.append("")
            lines.append(f"[bold]S3 Buckets ({len(s['s3_buckets'])}):[/bold]")
            for b in s["s3_buckets"]:
                flags = []
                if b.get("cloudfront"):
                    flags.append("CF")
                if b.get("cors"):
                    flags.append("CORS")
                if b.get("public_read"):
                    flags.append("public")
                flag_str = f" [{', '.join(flags)}]" if flags else ""
                lines.append(f"  • {b['name']}{flag_str}")

        lines.append("")
        lines.append(f"[bold]ALB:[/bold] {s.get('alb_mode', 'shared')}")

        if s.get("secrets"):
            lines.append("")
            lines.append(f"[bold]Secrets ({len(s['secrets'])}):[/bold]")
            for sec in s["secrets"]:
                lines.append(f"  • {sec['name']} ({sec['source']})")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "confirm":
            config = self._build_config()
            self.app.finish(config)

    def _build_config(self) -> ProjectConfig:
        s = self._state

        services = [
            ServiceConfig(
                name=svc["name"],
                dockerfile=svc.get("dockerfile", "Dockerfile"),
                build_context=svc.get("build_context", "."),
                port=svc.get("port"),
                domain=svc.get("domain"),
                health_check_path=svc.get("health_check_path", "/health"),
                command=svc.get("command"),
            )
            for svc in s["services"]
        ]

        rds = None
        if s.get("rds"):
            r = s["rds"]
            rds = RdsConfig(
                database_name=r["database_name"],
                instance_type=r.get("instance_type", "t4g.micro"),
                allocated_storage_gb=r.get("allocated_storage_gb", 20),
                expose_to=r.get("expose_to", []),
            )

        s3_buckets = [
            S3BucketConfig(
                name=b["name"],
                public_read=b.get("public_read", False),
                cloudfront=b.get("cloudfront", False),
                cors=b.get("cors", False),
            )
            for b in s.get("s3_buckets", [])
        ]

        secrets = [
            SecretConfig(
                name=sec["name"],
                source=SecretSource(sec.get("source", "generate")),
                length=sec.get("length", 50),
                generate_once=sec.get("generate_once", True),
            )
            for sec in s.get("secrets", [])
        ]

        alb = AlbConfig(
            mode=AlbMode(s.get("alb_mode", "shared")),
            shared_alb_name=s.get("shared_alb_name", ""),
            certificate_arn=s.get("certificate_arn"),
        )

        return ProjectConfig(
            project_name=s["project_name"],
            aws_region=s["aws_region"],
            vpc_name=s["vpc_name"],
            environments=s["environments"],
            services=services,
            rds=rds,
            s3_buckets=s3_buckets,
            alb=alb,
            secrets=secrets,
        )
