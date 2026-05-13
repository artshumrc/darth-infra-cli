"""Review screen — summary and confirm."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from ..step_rail import StepRail

from ...config.models import (
    AlbConfig,
    AlbMode,
    AlbPathRule,
    Architecture,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    CloudFrontConnection,
    CloudFrontCookiesMode,
    CloudFrontQueryStringsMode,
    EbsVolumeConfig,
    EnvironmentOverride,
    LaunchType,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    S3BucketConnection,
    S3BucketMode,
    SecretConfig,
    SecretSource,
    ServiceConfig,
    UlimitConfig,
)


def build_config_from_state(state: dict) -> ProjectConfig:
    s = state
    raw_environment_overrides = s.get("environment_overrides", {})

    service_names = [svc["name"] for svc in s.get("services", [])]
    resolved_service_secrets: dict[str, list[str]] = {
        name: [str(sec) for sec in svc.get("secrets", [])]
        for name, svc in ((svc["name"], svc) for svc in s.get("services", []))
    }
    for sec in s.get("secrets", []):
        sec_name = str(sec.get("name", "")).strip()
        if not sec_name:
            continue
        for svc_name in sec.get("expose_to", []):
            if svc_name not in service_names:
                continue
            if sec_name not in resolved_service_secrets[svc_name]:
                resolved_service_secrets[svc_name].append(sec_name)

    services = [
        ServiceConfig(
            name=svc["name"],
            dockerfile=svc.get("dockerfile", "Dockerfile"),
            build_context=svc.get("build_context", "."),
            docker_build_target=svc.get("docker_build_target"),
            image=svc.get("image"),
            port=svc.get("port"),
            health_check_path=svc.get("health_check_path", "/health"),
            health_check_http_codes=svc.get("health_check_http_codes", "200-399"),
            health_check_timeout_seconds=svc.get("health_check_timeout_seconds", 5),
            health_check_interval_seconds=svc.get("health_check_interval_seconds", 30),
            healthy_threshold_count=svc.get("healthy_threshold_count", 5),
            unhealthy_threshold_count=svc.get("unhealthy_threshold_count", 2),
            health_check_grace_period_seconds=svc.get(
                "health_check_grace_period_seconds"
            ),
            cpu=svc.get("cpu", 256),
            memory_mib=svc.get("memory_mib", 512),
            command=svc.get("command"),
            secrets=resolved_service_secrets.get(svc["name"], []),
            launch_type=LaunchType(svc.get("launch_type", "fargate")),
            ec2_instance_type=svc.get("ec2_instance_type"),
            user_data_script=svc.get("user_data_script"),
            user_data_script_content=svc.get("user_data_script_content"),
            ebs_volumes=[
                EbsVolumeConfig(
                    name=v["name"],
                    size_gb=v["size_gb"],
                    mount_path=v["mount_path"],
                    device_name=v.get("device_name", "/dev/xvdf"),
                    volume_type=v.get("volume_type", "gp3"),
                    filesystem_type=v.get("filesystem_type", "ext4"),
                )
                for v in svc.get("ebs_volumes", [])
            ],
            ulimits=[
                UlimitConfig(
                    name=u["name"],
                    soft_limit=u["soft_limit"],
                    hard_limit=u["hard_limit"],
                )
                for u in svc.get("ulimits", [])
            ],
            environment_variables=svc.get("environment_variables", {}),
            enable_ses_send_email=svc.get("enable_ses_send_email", False),
            enable_service_discovery=svc.get("enable_service_discovery", False),
        )
        for svc in s["services"]
    ]

    rds = None
    if s.get("rds"):
        r = s["rds"]
        rds = RdsConfig(
            database_name=r["database_name"],
            instance_type=r.get("instance_type", "db.t4g.micro"),
            allocated_storage_gb=r.get("allocated_storage_gb", 20),
            expose_to=r.get("expose_to", []),
        )

    s3_buckets = []
    for b in s.get("s3_buckets", []):
        flat_connections: list[S3BucketConnection] = []
        for conn in b.get("connections", []):
            conn_services = conn.get("services")
            if isinstance(conn_services, list) and conn_services:
                connection_services = [str(service) for service in conn_services]
            else:
                service_name = str(conn.get("service", "")).strip()
                connection_services = [service_name] if service_name else []

            for service_name in connection_services:
                flat_connections.append(
                    S3BucketConnection(
                        service=service_name,
                        env_key=conn["env_key"],
                        cloudfront_env_key=conn.get("cloudfront_env_key"),
                        read_only=conn.get("read_only", False),
                    )
                )

        s3_buckets.append(
            S3BucketConfig(
                name=b["name"],
                mode=S3BucketMode(b.get("mode", "managed")),
                existing_bucket_name=b.get("existing_bucket_name"),
                seed_source_bucket_name=b.get("seed_source_bucket_name"),
                seed_non_prod_only=b.get("seed_non_prod_only", True),
                public_read=b.get("public_read", False),
                cloudfront=b.get("cloudfront", False),
                cors=b.get("cors", False),
                connections=flat_connections,
            )
        )

    secrets = [
        SecretConfig(
            name=sec["name"],
            source=SecretSource(sec.get("source", "generate")),
            existing_secret_name=sec.get("existing_secret_name"),
            length=sec.get("length", 50),
            generate_once=sec.get("generate_once", True),
        )
        for sec in s.get("secrets", [])
    ]

    alb = AlbConfig(
        mode=AlbMode(s.get("alb_mode", "shared")),
        shared_alb_name=s.get("shared_alb_name", ""),
        shared_listener_arn=s.get("shared_listener_arn"),
        shared_alb_security_group_id=s.get("shared_alb_security_group_id"),
        certificate_arn=s.get("certificate_arn"),
        domain=s.get("alb_domain"),
        default_target_service=s.get("default_target_service"),
        default_listener_priority=(
            int(s["default_listener_priority"])
            if s.get("default_listener_priority") is not None
            and str(s.get("default_listener_priority")).strip() != ""
            else None
        ),
        path_rules=[
            AlbPathRule(
                name=rule["name"],
                path_pattern=rule["path_pattern"],
                target_service=rule["target_service"],
                priority=int(rule["priority"]),
            )
            for rule in s.get("alb_path_rules", [])
        ],
    )
    cloudfront = CloudFrontConfig(
        enabled=s.get("cloudfront_enabled", False),
        origin_https_only=s.get("cloudfront_origin_https_only", False),
        custom_domain=s.get("cloudfront_custom_domain"),
        certificate_arn=s.get("cloudfront_certificate_arn"),
        price_class=s.get("cloudfront_price_class", "PriceClass_100"),
        comment=s.get("cloudfront_comment"),
        connections=[
            CloudFrontConnection(
                service=conn["service"],
                env_key=conn["env_key"],
            )
            for conn in s.get("cloudfront_connections", [])
        ],
        cached_behaviors=[
            CloudFrontCachedBehavior(
                name=behavior["name"],
                path_pattern=behavior["path_pattern"],
                compress=behavior.get("compress", True),
                cache_by_origin_headers=behavior.get("cache_by_origin_headers", True),
                min_ttl_seconds=int(behavior.get("min_ttl_seconds", 0)),
                default_ttl_seconds=int(behavior.get("default_ttl_seconds", 3600)),
                max_ttl_seconds=int(behavior.get("max_ttl_seconds", 31536000)),
                query_strings=CloudFrontQueryStringsMode(
                    behavior.get("query_strings", "all")
                ),
                query_string_allowlist=list(behavior.get("query_string_allowlist", [])),
                cookies=CloudFrontCookiesMode(behavior.get("cookies", "none")),
                cookie_allowlist=list(behavior.get("cookie_allowlist", [])),
                forward_authorization_header=behavior.get(
                    "forward_authorization_header", False
                ),
            )
            for behavior in s.get("cloudfront_cached_behaviors", [])
        ],
    )
    environment_overrides: dict[str, EnvironmentOverride] = {}
    for env_name in s.get("environments", []):
        raw_override = raw_environment_overrides.get(env_name, {})
        if not isinstance(raw_override, dict):
            continue

        instance_type_override = raw_override.get("instance_type_override")
        ec2_instance_type_override = {
            str(service_name): str(instance_type)
            for service_name, instance_type in raw_override.get(
                "ec2_instance_type_override", {}
            ).items()
            if str(service_name).strip() and str(instance_type).strip()
        }
        tags = {
            str(key): str(value)
            for key, value in raw_override.get("tags", {}).items()
            if str(key).strip() and str(value).strip()
        }

        if instance_type_override or ec2_instance_type_override or tags:
            environment_overrides[env_name] = EnvironmentOverride(
                instance_type_override=(
                    str(instance_type_override) if instance_type_override else None
                ),
                ec2_instance_type_override=ec2_instance_type_override,
                tags=tags,
            )

    return ProjectConfig(
        project_name=s["project_name"],
        aws_region=s["aws_region"],
        vpc_name=s["vpc_name"],
        vpc_id=(
            None
            if s.get("vpc_id") in {None, "", False, "Select.NULL", "Select.BLANK"}
            else str(s.get("vpc_id"))
        ),
        private_subnet_ids=s.get("private_subnet_ids", []),
        public_subnet_ids=s.get("public_subnet_ids", []),
        environments=s["environments"],
        services=services,
        rds=rds,
        s3_buckets=s3_buckets,
        cloudfront=cloudfront,
        alb=alb,
        secrets=secrets,
        environment_overrides=environment_overrides,
        tags={
            str(key): str(value)
            for key, value in s.get("project_tags", {}).items()
            if str(key).strip() and str(value).strip()
        },
    )


class ReviewScreen(Screen):
    """Final screen: display project summary and confirm scaffolding."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield StepRail("review")
            yield Static("Review & Confirm", classes="title")
            with VerticalScroll():
                yield Static(self._build_summary(), id="summary")
            with Vertical(classes="button-row"):
                yield Button("Create Project ✓", id="confirm", variant="primary")

    def _build_summary(self) -> str:
        s = self._state
        resolved_service_secrets = self._resolve_service_secrets()
        lines = [
            f"[bold]Project:[/bold] {s['project_name']}",
            f"[bold]Region:[/bold]  {s['aws_region']}",
            f"[bold]VPC:[/bold]     {s['vpc_name']}",
            f"[bold]VPC ID:[/bold]  {s.get('vpc_id') or '(auto)'}",
            f"[bold]Envs:[/bold]    {', '.join(s['environments'])}",
        ]
        project_tags = s.get("project_tags", {})
        if project_tags:
            lines.append(f"[bold]Project Tags:[/bold] {len(project_tags)}")
            for key, value in sorted(project_tags.items()):
                lines.append(f"  {key}={value}")

        environment_overrides = s.get("environment_overrides", {})
        tagged_envs = [
            env_name
            for env_name in s.get("environments", [])
            if environment_overrides.get(env_name, {}).get("tags")
        ]
        if tagged_envs:
            lines.append("")
            lines.append("[bold]Environment Tags:[/bold]")
            for env_name in tagged_envs:
                lines.append(f"  {env_name}:")
                for key, value in sorted(
                    environment_overrides.get(env_name, {}).get("tags", {}).items()
                ):
                    lines.append(f"    {key}={value}")

        lines.extend(
            [
                "",
                f"[bold]Services ({len(s['services'])}):[/bold]",
            ]
        )
        for svc in s["services"]:
            port_info = f":{svc['port']}" if svc.get("port") else " (worker)"
            lt_info = ""
            if svc.get("launch_type") == "ec2":
                lt_info = f" [EC2: {svc.get('ec2_instance_type', '?')}]"
            disc_info = " [discovery]" if svc.get("enable_service_discovery") else ""
            image_info = f" [image: {svc['image']}]" if svc.get("image") else ""
            lines.append(
                f"  • {svc['name']}{port_info}{lt_info}{disc_info}{image_info}"
            )
            lines.append(
                f"    CPU: {svc.get('cpu', 256)} | Memory: {svc.get('memory_mib', 512)} MiB"
            )
            lines.append(
                f"    Health check: {svc.get('health_check_path', '/health')} "
                f"[{svc.get('health_check_http_codes', '200-399')}]"
            )
            lines.append(
                "    Health timing: "
                f"timeout={svc.get('health_check_timeout_seconds', 5)}s "
                f"interval={svc.get('health_check_interval_seconds', 30)}s "
                f"healthy={svc.get('healthy_threshold_count', 5)} "
                f"unhealthy={svc.get('unhealthy_threshold_count', 2)} "
                f"grace={svc.get('health_check_grace_period_seconds') or 0}s"
            )
            if svc.get("user_data_script"):
                lines.append(f"    User data: {svc['user_data_script']}")
            if svc.get("user_data_script_content"):
                line_count = len(str(svc["user_data_script_content"]).splitlines())
                lines.append(f"    User data inline script: {line_count} lines")
            if svc.get("ebs_volumes"):
                for vol in svc["ebs_volumes"]:
                    lines.append(
                        f"    EBS: {vol['name']} "
                        f"({vol['size_gb']}G → {vol['mount_path']}, "
                        f"{vol.get('filesystem_type', 'ext4')})"
                    )
            if svc.get("ulimits"):
                for ul in svc["ulimits"]:
                    lines.append(
                        f"    Ulimit: {ul['name']} "
                        f"(soft={ul['soft_limit']}, hard={ul['hard_limit']})"
                    )
            if svc.get("environment_variables"):
                for k, v in svc["environment_variables"].items():
                    lines.append(f"    Env: {k}={v}")
            service_secrets = resolved_service_secrets.get(svc["name"], [])
            if service_secrets:
                lines.append(f"    Service secrets: {', '.join(service_secrets)}")

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
                mode = b.get("mode", "managed")
                lines.append(f"  • {b['name']} ({mode}){flag_str}")
                if mode == "existing":
                    lines.append(
                        f"      existing: {b.get('existing_bucket_name') or '(missing)'}"
                    )
                if mode == "seed-copy":
                    lines.append(
                        f"      seed source: {b.get('seed_source_bucket_name') or '(missing)'}"
                    )
                    lines.append(
                        "      seed scope: "
                        + (
                            "non-prod only"
                            if b.get("seed_non_prod_only", True)
                            else "all environments"
                        )
                    )
                for conn in b.get("connections", []):
                    access = "read-only" if conn.get("read_only") else "R/W"
                    conn_services = conn.get("services")
                    if isinstance(conn_services, list) and conn_services:
                        service_label = ", ".join(
                            str(service) for service in conn_services
                        )
                    else:
                        service_label = str(conn.get("service", "")).strip()
                    lines.append(
                        f"      → {service_label} as {conn['env_key']} [{access}]"
                    )
                    if conn.get("cloudfront_env_key"):
                        lines.append(f"        CF URL → {conn['cloudfront_env_key']}")

        lines.append("")
        lines.append(f"[bold]ALB:[/bold] {s.get('alb_mode', 'shared')}")
        lines.append(f"  Cluster domain: {s.get('alb_domain') or '(none)'}")
        lines.append(f"  Default target: {s.get('default_target_service') or '(none)'}")
        lines.append(
            f"  Default priority: {s.get('default_listener_priority') or '(none)'}"
        )
        if s.get("alb_path_rules"):
            lines.append("  Path rules:")
            for rule in s.get("alb_path_rules", []):
                lines.append(
                    f"    - {rule.get('name')}: {rule.get('path_pattern')} -> "
                    f"{rule.get('target_service')} ({rule.get('priority')})"
                )
        if s.get("alb_mode", "shared") == "shared":
            lines.append(f"  Name: {s.get('shared_alb_name') or '(auto)'}")
            lines.append(f"  Listener: {s.get('shared_listener_arn') or '(auto)'}")
            lines.append(
                f"  ALB SG: {s.get('shared_alb_security_group_id') or '(auto)'}"
            )

        lines.append("")
        cf_enabled = bool(s.get("cloudfront_enabled", False))
        lines.append(
            f"[bold]CloudFront:[/bold] {'enabled' if cf_enabled else 'disabled'}"
        )
        if cf_enabled:
            lines.append(
                "  ALB origin protocol: "
                f"{'https-only' if s.get('cloudfront_origin_https_only', False) else 'http-only'}"
            )
            lines.append(
                f"  Custom domain: {s.get('cloudfront_custom_domain') or '(none)'}"
            )
            lines.append(
                f"  Certificate ARN: {s.get('cloudfront_certificate_arn') or '(none)'}"
            )
            lines.append(
                f"  Price class: {s.get('cloudfront_price_class', 'PriceClass_100')}"
            )
            lines.append(f"  Comment: {s.get('cloudfront_comment') or '(none)'}")
            lines.append(
                f"  Service connections: {len(s.get('cloudfront_connections', []))}"
            )
            lines.append(
                f"  Cached behaviors: {len(s.get('cloudfront_cached_behaviors', []))}"
            )

        if s.get("secrets"):
            lines.append("")
            lines.append(f"[bold]Secrets ({len(s['secrets'])}):[/bold]")
            for sec in s["secrets"]:
                expose = sec.get("expose_to", [])
                expose_suffix = f" -> {', '.join(expose)}" if expose else ""
                lines.append(f"  • {sec['name']} ({sec['source']}){expose_suffix}")

        return "\n".join(lines)

    def _resolve_service_secrets(self) -> dict[str, list[str]]:
        """Resolve per-service secret attachments from both screens."""
        service_names = [svc["name"] for svc in self._state.get("services", [])]
        out: dict[str, list[str]] = {
            name: [str(sec) for sec in svc.get("secrets", [])]
            for name, svc in (
                (svc["name"], svc) for svc in self._state.get("services", [])
            )
        }

        for sec in self._state.get("secrets", []):
            sec_name = str(sec.get("name", "")).strip()
            if not sec_name:
                continue
            for svc_name in sec.get("expose_to", []):
                if svc_name not in service_names:
                    continue
                if sec_name not in out[svc_name]:
                    out[svc_name].append(sec_name)
        return out

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return
        if event.button.id == "back":
            self._state["_wizard_last_screen"] = "tags"
            self.app.pop_screen()
        elif event.button.id == "confirm":
            config = self._build_config()
            self.app.finish(config)

    def _build_config(self) -> ProjectConfig:
        return build_config_from_state(self._state)
