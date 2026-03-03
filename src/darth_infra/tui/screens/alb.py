"""Routing configuration screen."""

from __future__ import annotations

import threading

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    Switch,
)

from ..step_rail import StepRail


class AlbScreen(Screen):
    """Configure listener routing using shared ALB settings."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._priority_fetch_inflight = False
        self._path_rules: list[dict] = []
        self._editing_path_rule_index: int | None = None
        self._cloudfront_connections: list[dict] = []
        self._editing_cloudfront_conn_index: int | None = None
        self._cloudfront_cached_behaviors: list[dict] = []
        self._editing_cloudfront_behavior_index: int | None = None
        self._cloudfront_certs_fetch_inflight = False
        self._cloudfront_cert_options: list[tuple[str, str]] = []

    def _draft(self) -> dict:
        d = self._state.setdefault("_wizard_draft", {})
        return d.setdefault("alb", {})

    @staticmethod
    def _is_select_empty(value: object) -> bool:
        null_sentinel = getattr(Select, "NULL", object())
        blank_sentinel = getattr(Select, "BLANK", object())
        return value in {None, "", False, null_sentinel, blank_sentinel}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Path Rules", classes="title")
                yield ListView(id="path-rule-list")
            with VerticalScroll(classes="form-container"):
                yield StepRail("alb")
                yield Static("Routing", classes="title")
                yield Static(
                    "Shared ALB values are managed on the Resources step.",
                )

                yield Static("Cluster Routing", classes="title")
                yield Static("Default Listener Rule", classes="title")
                yield Label("Cluster domain:", classes="section-label")
                yield Input(placeholder="example.com", id="alb_domain")
                yield Label("Default target service:", classes="section-label")
                yield Select(
                    [],
                    id="default_target_service",
                    prompt="Select service",
                    allow_blank=True,
                )
                yield Label("Default rule priority:", classes="section-label")
                yield Input(placeholder="100", id="default_listener_priority")
                yield Button(
                    "Get Next Available Priority",
                    id="fetch_next_priority_default",
                    variant="default",
                )

                yield Static("Optional Additional Path Rules", classes="title")
                yield Label("Rule name:", classes="section-label")
                yield Input(placeholder="kibana", id="path_rule_name")
                yield Label("Path pattern:", classes="section-label")
                yield Input(placeholder="/kibana/*", id="path_rule_pattern")
                yield Label("Target service:", classes="section-label")
                yield Select(
                    [],
                    id="path_rule_target_service",
                    prompt="Select service",
                    allow_blank=True,
                )
                yield Label("Priority:", classes="section-label")
                yield Input(placeholder="101", id="path_rule_priority")
                with Vertical(classes="button-row"):
                    yield Button(
                        "+ Add / Update Rule", id="path_rule_add", variant="success"
                    )
                    yield Button("Remove Rule", id="path_rule_remove", variant="error")
                yield Button(
                    "Get Next Available Priority",
                    id="fetch_next_priority_rule",
                    variant="default",
                )

                yield Static("CloudFront (ALB Front Door)", classes="title")
                yield Label("Enable CloudFront:", classes="section-label")
                yield Switch(False, id="cloudfront_enabled")
                yield Label("ALB origin HTTPS only:", classes="section-label")
                yield Switch(False, id="cloudfront_origin_https_only")
                yield Label("CloudFront custom domain (optional):", classes="section-label")
                yield Input(placeholder="cdn.example.com", id="cloudfront_custom_domain")
                yield Label(
                    "CloudFront ACM certificate (optional):",
                    classes="section-label",
                )
                yield Select(
                    [],
                    id="cloudfront_certificate_arn",
                    prompt="Select certificate",
                    allow_blank=True,
                )
                yield Button(
                    "Fetch Certificates (us-east-1)",
                    id="cloudfront_fetch_certificates",
                    variant="default",
                )
                yield Label("Price class:", classes="section-label")
                yield Select(
                    [
                        ("PriceClass_100", "PriceClass_100"),
                        ("PriceClass_200", "PriceClass_200"),
                        ("PriceClass_All", "PriceClass_All"),
                    ],
                    id="cloudfront_price_class",
                    prompt="Select price class",
                )
                yield Label("Comment (optional):", classes="section-label")
                yield Input(
                    placeholder="edge cache distribution for app traffic",
                    id="cloudfront_comment",
                )

                yield Static("CloudFront Service Connections", classes="title")
                yield ListView(id="cloudfront-conn-list")
                yield Label("Target service:", classes="section-label")
                yield Select(
                    [],
                    id="cloudfront_conn_service",
                    prompt="Select service",
                    allow_blank=True,
                )
                yield Label("CloudFront URL env var key:", classes="section-label")
                yield Input(placeholder="APP_CDN_URL", id="cloudfront_conn_env_key")
                with Vertical(classes="button-row"):
                    yield Button(
                        "+ Add / Update Connection",
                        id="cloudfront_conn_add",
                        variant="success",
                    )
                    yield Button(
                        "Remove Connection",
                        id="cloudfront_conn_remove",
                        variant="error",
                    )

                yield Static("CloudFront Cached Behaviors", classes="title")
                yield ListView(id="cloudfront-behavior-list")
                yield Label("Behavior name:", classes="section-label")
                yield Input(placeholder="images", id="cloudfront_behavior_name")
                yield Label("Path pattern:", classes="section-label")
                yield Input(placeholder="/images/*", id="cloudfront_behavior_path")
                yield Label("Query string mode:", classes="section-label")
                yield Select(
                    [
                        ("all", "all"),
                        ("none", "none"),
                        ("allowlist", "allowlist"),
                    ],
                    id="cloudfront_behavior_query_mode",
                )
                yield Label("Query allowlist (comma separated):", classes="section-label")
                yield Input(
                    placeholder="region,size",
                    id="cloudfront_behavior_query_allowlist",
                )
                yield Label("Cookie mode:", classes="section-label")
                yield Select(
                    [
                        ("none", "none"),
                        ("all", "all"),
                        ("allowlist", "allowlist"),
                    ],
                    id="cloudfront_behavior_cookie_mode",
                )
                yield Label("Cookie allowlist (comma separated):", classes="section-label")
                yield Input(
                    placeholder="sessionid",
                    id="cloudfront_behavior_cookie_allowlist",
                )
                yield Label("Min TTL seconds:", classes="section-label")
                yield Input(placeholder="0", id="cloudfront_behavior_min_ttl")
                yield Label("Default TTL seconds:", classes="section-label")
                yield Input(placeholder="3600", id="cloudfront_behavior_default_ttl")
                yield Label("Max TTL seconds:", classes="section-label")
                yield Input(placeholder="31536000", id="cloudfront_behavior_max_ttl")
                yield Label("Compress responses:", classes="section-label")
                yield Switch(True, id="cloudfront_behavior_compress")
                yield Label("Honor origin cache headers:", classes="section-label")
                yield Switch(True, id="cloudfront_behavior_cache_by_origin_headers")
                yield Label("Forward Authorization header:", classes="section-label")
                yield Switch(False, id="cloudfront_behavior_forward_auth")
                with Vertical(classes="button-row"):
                    yield Button(
                        "+ Add / Update Behavior",
                        id="cloudfront_behavior_add",
                        variant="success",
                    )
                    yield Button(
                        "Remove Behavior",
                        id="cloudfront_behavior_remove",
                        variant="error",
                    )

    def on_mount(self) -> None:
        self._restore_from_draft()
        self._restore_cloudfront_certificate_options()
        self._refresh_path_rule_sidebar()
        self._refresh_target_service_selects()
        self._refresh_cloudfront_connection_sidebar()
        self._refresh_cloudfront_behavior_sidebar()
        self._refresh_cloudfront_certificate_select()
        draft = self._draft()
        price_class = str(
            draft.get(
                "cloudfront_price_class",
                self._state.get("cloudfront_price_class", "PriceClass_100"),
            )
        )
        self.query_one("#cloudfront_price_class", Select).value = price_class
        query_mode = str(draft.get("cloudfront_behavior_query_mode", "all"))
        self.query_one("#cloudfront_behavior_query_mode", Select).value = query_mode
        cookie_mode = str(draft.get("cloudfront_behavior_cookie_mode", "none"))
        self.query_one("#cloudfront_behavior_cookie_mode", Select).value = cookie_mode

    def _restore_from_draft(self) -> None:
        draft = self._draft()
        self.query_one("#alb_domain", Input).value = str(
            draft.get("alb_domain", self._state.get("alb_domain") or "")
        )
        self.query_one("#default_listener_priority", Input).value = str(
            draft.get(
                "default_listener_priority",
                self._state.get("default_listener_priority") or "",
            )
        )
        if isinstance(draft.get("alb_path_rules"), list):
            self._path_rules = [dict(v) for v in draft.get("alb_path_rules", [])]
        elif isinstance(self._state.get("alb_path_rules"), list):
            self._path_rules = [dict(v) for v in self._state.get("alb_path_rules", [])]
        if isinstance(draft.get("cloudfront_connections"), list):
            self._cloudfront_connections = [
                dict(v) for v in draft.get("cloudfront_connections", [])
            ]
        elif isinstance(self._state.get("cloudfront_connections"), list):
            self._cloudfront_connections = [
                dict(v) for v in self._state.get("cloudfront_connections", [])
            ]
        if isinstance(draft.get("cloudfront_cached_behaviors"), list):
            self._cloudfront_cached_behaviors = [
                dict(v) for v in draft.get("cloudfront_cached_behaviors", [])
            ]
        elif isinstance(self._state.get("cloudfront_cached_behaviors"), list):
            self._cloudfront_cached_behaviors = [
                dict(v) for v in self._state.get("cloudfront_cached_behaviors", [])
            ]

        if draft.get("path_rule_name") is not None:
            self.query_one("#path_rule_name", Input).value = str(
                draft.get("path_rule_name", "")
            )
        if draft.get("path_rule_pattern") is not None:
            self.query_one("#path_rule_pattern", Input).value = str(
                draft.get("path_rule_pattern", "")
            )
        if draft.get("path_rule_priority") is not None:
            self.query_one("#path_rule_priority", Input).value = str(
                draft.get("path_rule_priority", "")
            )
        self.query_one("#cloudfront_enabled", Switch).value = bool(
            draft.get(
                "cloudfront_enabled",
                self._state.get("cloudfront_enabled", False),
            )
        )
        self.query_one("#cloudfront_origin_https_only", Switch).value = bool(
            draft.get(
                "cloudfront_origin_https_only",
                self._state.get("cloudfront_origin_https_only", False),
            )
        )
        self.query_one("#cloudfront_custom_domain", Input).value = str(
            draft.get(
                "cloudfront_custom_domain",
                self._state.get("cloudfront_custom_domain") or "",
            )
        )
        self.query_one("#cloudfront_comment", Input).value = str(
            draft.get(
                "cloudfront_comment",
                self._state.get("cloudfront_comment") or "",
            )
        )
        self.query_one("#cloudfront_behavior_name", Input).value = str(
            draft.get("cloudfront_behavior_name", "")
        )
        self.query_one("#cloudfront_behavior_path", Input).value = str(
            draft.get("cloudfront_behavior_path", "")
        )
        self.query_one("#cloudfront_behavior_query_allowlist", Input).value = str(
            draft.get("cloudfront_behavior_query_allowlist", "")
        )
        self.query_one("#cloudfront_behavior_cookie_allowlist", Input).value = str(
            draft.get("cloudfront_behavior_cookie_allowlist", "")
        )
        self.query_one("#cloudfront_behavior_min_ttl", Input).value = str(
            draft.get("cloudfront_behavior_min_ttl", "")
        )
        self.query_one("#cloudfront_behavior_default_ttl", Input).value = str(
            draft.get("cloudfront_behavior_default_ttl", "")
        )
        self.query_one("#cloudfront_behavior_max_ttl", Input).value = str(
            draft.get("cloudfront_behavior_max_ttl", "")
        )
        self.query_one("#cloudfront_behavior_compress", Switch).value = bool(
            draft.get("cloudfront_behavior_compress", True)
        )
        self.query_one(
            "#cloudfront_behavior_cache_by_origin_headers", Switch
        ).value = bool(draft.get("cloudfront_behavior_cache_by_origin_headers", True))
        self.query_one("#cloudfront_behavior_forward_auth", Switch).value = bool(
            draft.get("cloudfront_behavior_forward_auth", False)
        )
        self.query_one("#cloudfront_conn_env_key", Input).value = str(
            draft.get("cloudfront_conn_env_key", "")
        )

    def _refresh_path_rule_sidebar(self) -> None:
        lv = self.query_one("#path-rule-list", ListView)
        lv.clear()
        for rule in self._path_rules:
            lv.append(
                ListItem(
                    Static(
                        f"{rule['name']}: {rule['path_pattern']} -> "
                        f"{rule['target_service']} ({rule['priority']})",
                        markup=False,
                    )
                )
            )

    def _refresh_cloudfront_connection_sidebar(self) -> None:
        lv = self.query_one("#cloudfront-conn-list", ListView)
        lv.clear()
        for conn in self._cloudfront_connections:
            lv.append(
                ListItem(
                    Static(f"{conn['service']} -> {conn['env_key']}", markup=False)
                )
            )

    def _refresh_cloudfront_behavior_sidebar(self) -> None:
        lv = self.query_one("#cloudfront-behavior-list", ListView)
        lv.clear()
        for behavior in self._cloudfront_cached_behaviors:
            lv.append(
                ListItem(
                    Static(
                        f"{behavior['name']}: {behavior['path_pattern']} "
                        f"[q={behavior['query_strings']}, c={behavior['cookies']}]",
                        markup=False,
                    )
                )
            )

    def _refresh_target_service_selects(self) -> None:
        services = [s["name"] for s in self._state.get("services", []) if s.get("port")]
        all_services = [s["name"] for s in self._state.get("services", [])]
        options = [(svc, svc) for svc in services]

        default_select = self.query_one("#default_target_service", Select)
        current_default = default_select.value
        default_select.set_options(options)
        desired_default = self._draft().get(
            "default_target_service",
            self._state.get("default_target_service"),
        )
        if desired_default and desired_default in services:
            default_select.value = desired_default
        elif not self._is_select_empty(current_default) and current_default in services:
            default_select.value = current_default
        else:
            default_select.clear()

        rule_select = self.query_one("#path_rule_target_service", Select)
        current_rule_target = rule_select.value
        rule_select.set_options(options)
        desired_target = self._draft().get("path_rule_target_service")
        if desired_target and desired_target in services:
            rule_select.value = desired_target
        elif (
            not self._is_select_empty(current_rule_target)
            and current_rule_target in services
        ):
            rule_select.value = current_rule_target
        else:
            rule_select.clear()

        conn_select = self.query_one("#cloudfront_conn_service", Select)
        current_conn_service = conn_select.value
        conn_select.set_options([(svc, svc) for svc in all_services])
        desired_conn_service = self._draft().get("cloudfront_conn_service")
        if desired_conn_service and desired_conn_service in all_services:
            conn_select.value = desired_conn_service
        elif (
            not self._is_select_empty(current_conn_service)
            and current_conn_service in all_services
        ):
            conn_select.value = current_conn_service
        else:
            conn_select.clear()

    def _restore_cloudfront_certificate_options(self) -> None:
        draft_options = self._draft().get("cloudfront_certificate_options")
        state_options = self._state.get("cloudfront_certificate_options")
        source_options = draft_options if isinstance(draft_options, list) else state_options
        if not isinstance(source_options, list):
            self._cloudfront_cert_options = []
            return
        options: list[tuple[str, str]] = []
        for entry in source_options:
            if not isinstance(entry, dict):
                continue
            arn = str(entry.get("arn", "")).strip()
            label = str(entry.get("label", "")).strip()
            if arn and label:
                options.append((label, arn))
        self._cloudfront_cert_options = options

    def _selected_cloudfront_certificate_arn(self) -> str | None:
        cert_value = self.query_one("#cloudfront_certificate_arn", Select).value
        if self._is_select_empty(cert_value):
            return None
        arn = str(cert_value).strip()
        return arn or None

    def _refresh_cloudfront_certificate_select(self) -> None:
        cert_select = self.query_one("#cloudfront_certificate_arn", Select)
        options = list(self._cloudfront_cert_options)
        option_arns = {value for _, value in options}
        desired_cert_arn = str(
            self._draft().get(
                "cloudfront_certificate_arn",
                self._state.get("cloudfront_certificate_arn") or "",
            )
            or ""
        ).strip()
        if desired_cert_arn and desired_cert_arn not in option_arns:
            options.append((f"Manual: {desired_cert_arn}", desired_cert_arn))
        cert_select.set_options(options)
        if desired_cert_arn:
            cert_select.value = desired_cert_arn
        else:
            cert_select.clear()

    def _capture_draft(self) -> None:
        default_target = self.query_one("#default_target_service", Select).value
        path_target = self.query_one("#path_rule_target_service", Select).value
        conn_service = self.query_one("#cloudfront_conn_service", Select).value
        self._draft().update(
            {
                "alb_domain": self.query_one("#alb_domain", Input).value,
                "default_target_service": (
                    str(default_target)
                    if not self._is_select_empty(default_target)
                    else None
                ),
                "default_listener_priority": self.query_one(
                    "#default_listener_priority", Input
                ).value,
                "alb_path_rules": [dict(v) for v in self._path_rules],
                "path_rule_name": self.query_one("#path_rule_name", Input).value,
                "path_rule_pattern": self.query_one("#path_rule_pattern", Input).value,
                "path_rule_target_service": (
                    str(path_target) if not self._is_select_empty(path_target) else None
                ),
                "path_rule_priority": self.query_one(
                    "#path_rule_priority", Input
                ).value,
                "cloudfront_enabled": self.query_one(
                    "#cloudfront_enabled", Switch
                ).value,
                "cloudfront_origin_https_only": self.query_one(
                    "#cloudfront_origin_https_only", Switch
                ).value,
                "cloudfront_custom_domain": self.query_one(
                    "#cloudfront_custom_domain", Input
                ).value,
                "cloudfront_certificate_arn": (
                    self._selected_cloudfront_certificate_arn() or ""
                ),
                "cloudfront_certificate_options": [
                    {"label": label, "arn": arn}
                    for label, arn in self._cloudfront_cert_options
                ],
                "cloudfront_price_class": self.query_one(
                    "#cloudfront_price_class", Select
                ).value,
                "cloudfront_comment": self.query_one(
                    "#cloudfront_comment", Input
                ).value,
                "cloudfront_connections": [
                    dict(v) for v in self._cloudfront_connections
                ],
                "cloudfront_cached_behaviors": [
                    dict(v) for v in self._cloudfront_cached_behaviors
                ],
                "cloudfront_conn_service": (
                    str(conn_service)
                    if not self._is_select_empty(conn_service)
                    else None
                ),
                "cloudfront_conn_env_key": self.query_one(
                    "#cloudfront_conn_env_key", Input
                ).value,
                "cloudfront_behavior_name": self.query_one(
                    "#cloudfront_behavior_name", Input
                ).value,
                "cloudfront_behavior_path": self.query_one(
                    "#cloudfront_behavior_path", Input
                ).value,
                "cloudfront_behavior_query_mode": self.query_one(
                    "#cloudfront_behavior_query_mode", Select
                ).value,
                "cloudfront_behavior_query_allowlist": self.query_one(
                    "#cloudfront_behavior_query_allowlist", Input
                ).value,
                "cloudfront_behavior_cookie_mode": self.query_one(
                    "#cloudfront_behavior_cookie_mode", Select
                ).value,
                "cloudfront_behavior_cookie_allowlist": self.query_one(
                    "#cloudfront_behavior_cookie_allowlist", Input
                ).value,
                "cloudfront_behavior_min_ttl": self.query_one(
                    "#cloudfront_behavior_min_ttl", Input
                ).value,
                "cloudfront_behavior_default_ttl": self.query_one(
                    "#cloudfront_behavior_default_ttl", Input
                ).value,
                "cloudfront_behavior_max_ttl": self.query_one(
                    "#cloudfront_behavior_max_ttl", Input
                ).value,
                "cloudfront_behavior_compress": self.query_one(
                    "#cloudfront_behavior_compress", Switch
                ).value,
                "cloudfront_behavior_cache_by_origin_headers": self.query_one(
                    "#cloudfront_behavior_cache_by_origin_headers", Switch
                ).value,
                "cloudfront_behavior_forward_auth": self.query_one(
                    "#cloudfront_behavior_forward_auth", Switch
                ).value,
            }
        )

    def _persist_to_state(self) -> bool:
        if not self._validate_routing():
            return False
        self._capture_draft()
        self._state["alb_mode"] = "shared"
        self._state["alb_domain"] = (
            self.query_one("#alb_domain", Input).value.strip() or None
        )
        default_target = self.query_one("#default_target_service", Select).value
        self._state["default_target_service"] = (
            str(default_target).strip()
            if not self._is_select_empty(default_target)
            else None
        )
        default_priority = self.query_one(
            "#default_listener_priority", Input
        ).value.strip()
        self._state["default_listener_priority"] = (
            int(default_priority) if default_priority else None
        )
        self._state["alb_path_rules"] = [dict(v) for v in self._path_rules]
        self._state["cloudfront_enabled"] = self.query_one(
            "#cloudfront_enabled", Switch
        ).value
        price_value = self.query_one("#cloudfront_price_class", Select).value
        self._state["cloudfront_price_class"] = (
            str(price_value).strip()
            if not self._is_select_empty(price_value)
            else "PriceClass_100"
        )
        self._state["cloudfront_comment"] = (
            self.query_one("#cloudfront_comment", Input).value.strip() or None
        )
        if self._state["cloudfront_enabled"]:
            self._state["cloudfront_origin_https_only"] = self.query_one(
                "#cloudfront_origin_https_only", Switch
            ).value
            self._state["cloudfront_custom_domain"] = (
                self.query_one("#cloudfront_custom_domain", Input).value.strip() or None
            )
            self._state["cloudfront_certificate_arn"] = (
                self._selected_cloudfront_certificate_arn()
            )
            self._state["cloudfront_certificate_options"] = [
                {"label": label, "arn": arn}
                for label, arn in self._cloudfront_cert_options
            ]
            self._state["cloudfront_connections"] = [
                dict(v) for v in self._cloudfront_connections
            ]
            self._state["cloudfront_cached_behaviors"] = [
                dict(v) for v in self._cloudfront_cached_behaviors
            ]
        else:
            self._state["cloudfront_origin_https_only"] = False
            self._state["cloudfront_custom_domain"] = None
            self._state["cloudfront_certificate_arn"] = None
            self._state["cloudfront_connections"] = []
            self._state["cloudfront_cached_behaviors"] = []
        return True

    def _validate_routing(self) -> bool:
        domain = self.query_one("#alb_domain", Input).value.strip()
        target_value = self.query_one("#default_target_service", Select).value
        target = (
            str(target_value).strip()
            if not self._is_select_empty(target_value)
            else None
        )
        default_priority_raw = self.query_one(
            "#default_listener_priority", Input
        ).value.strip()
        if domain:
            if not target:
                self.notify(
                    "Default target service is required when cluster domain is set",
                    severity="error",
                )
                return False
            if not default_priority_raw:
                self.notify(
                    "Default listener priority is required when cluster domain is set",
                    severity="error",
                )
                return False
            try:
                default_priority = int(default_priority_raw)
            except ValueError:
                self.notify(
                    "Default listener priority must be an integer", severity="error"
                )
                return False
            if default_priority < 1 or default_priority > 50000:
                self.notify(
                    "Default listener priority must be between 1 and 50000",
                    severity="error",
                )
                return False
        else:
            if target or default_priority_raw or self._path_rules:
                self.notify(
                    "Cluster domain is required when default/path routing is configured",
                    severity="error",
                )
                return False
            return True

        priorities = {int(default_priority_raw)}
        names: set[str] = set()
        for rule in self._path_rules:
            name = str(rule.get("name", "")).strip()
            if not name:
                self.notify("Path rule name is required", severity="error")
                return False
            if name in names:
                self.notify(f"Duplicate path rule name '{name}'", severity="error")
                return False
            names.add(name)
            try:
                priority = int(rule.get("priority", 0))
            except (TypeError, ValueError):
                self.notify(
                    f"Path rule '{name}' has an invalid priority", severity="error"
                )
                return False
            if priority < 1 or priority > 50000:
                self.notify(
                    f"Path rule '{name}' priority must be between 1 and 50000",
                    severity="error",
                )
                return False
            if priority in priorities:
                self.notify(
                    f"Duplicate listener priority '{priority}' in routing rules",
                    severity="error",
                )
                return False
            priorities.add(priority)
        return self._validate_cloudfront()

    def _validate_cloudfront(self) -> bool:
        enabled = self.query_one("#cloudfront_enabled", Switch).value
        if not enabled:
            return True

        domain = self.query_one("#alb_domain", Input).value.strip()
        if not domain:
            self.notify(
                "Cluster domain is required when CloudFront is enabled",
                severity="error",
            )
            return False
        custom_domain = self.query_one("#cloudfront_custom_domain", Input).value.strip()
        cert_arn = self._selected_cloudfront_certificate_arn() or ""
        if bool(custom_domain) != bool(cert_arn):
            self.notify(
                "CloudFront custom domain and certificate must be set together",
                severity="error",
            )
            return False
        if custom_domain and ("://" in custom_domain or "/" in custom_domain):
            self.notify(
                "CloudFront custom domain must be a hostname without scheme/path",
                severity="error",
            )
            return False
        if custom_domain and cert_arn:
            self.notify(
                "CloudFront custom domain requires external DNS alias mapping to the distribution",
                severity="information",
            )

        origin_https_only = self.query_one("#cloudfront_origin_https_only", Switch).value
        if origin_https_only:
            mode = str(self._state.get("alb_mode", "shared")).strip() or "shared"
            if mode == "shared":
                listener_protocol = (
                    str(self._state.get("shared_listener_protocol") or "").strip().upper()
                )
                listener_port_raw = self._state.get("shared_listener_port")
                try:
                    listener_port = (
                        int(str(listener_port_raw).strip())
                        if listener_port_raw is not None
                        and str(listener_port_raw).strip()
                        else None
                    )
                except ValueError:
                    listener_port = None
                if listener_protocol != "HTTPS" or listener_port != 443:
                    listener_arn = str(self._state.get("shared_listener_arn") or "").strip()
                    if listener_arn and (
                        not listener_protocol or listener_port is None
                    ):
                        self.notify(
                            "Fetch shared ALB details to confirm listener protocol/port before using CloudFront HTTPS origin",
                            severity="error",
                        )
                    else:
                        self.notify(
                            "CloudFront HTTPS origin requires a shared ALB HTTPS listener on port 443",
                            severity="error",
                        )
                    return False

        if not self._cloudfront_cached_behaviors:
            self.notify(
                "Add at least one CloudFront cached behavior when enabled",
                severity="error",
            )
            return False

        behavior_names: set[str] = set()
        behavior_paths: set[str] = set()
        connection_pairs: set[tuple[str, str]] = set()
        for conn in self._cloudfront_connections:
            service = str(conn.get("service", "")).strip()
            env_key = str(conn.get("env_key", "")).strip()
            if not service or not env_key:
                self.notify(
                    "CloudFront connections require service and env var key",
                    severity="error",
                )
                return False
            pair = (service, env_key)
            if pair in connection_pairs:
                self.notify(
                    f"Duplicate CloudFront connection for {service} -> {env_key}",
                    severity="error",
                )
                return False
            connection_pairs.add(pair)

        for behavior in self._cloudfront_cached_behaviors:
            name = str(behavior.get("name", "")).strip()
            path = str(behavior.get("path_pattern", "")).strip()
            if not name or not path:
                self.notify(
                    "CloudFront behaviors require name and path pattern",
                    severity="error",
                )
                return False
            if name in behavior_names:
                self.notify(f"Duplicate CloudFront behavior name '{name}'", severity="error")
                return False
            if path in behavior_paths:
                self.notify(
                    f"Duplicate CloudFront behavior path pattern '{path}'",
                    severity="error",
                )
                return False
            behavior_names.add(name)
            behavior_paths.add(path)
            try:
                min_ttl = int(behavior.get("min_ttl_seconds", 0))
                default_ttl = int(behavior.get("default_ttl_seconds", 3600))
                max_ttl = int(behavior.get("max_ttl_seconds", 31536000))
            except (TypeError, ValueError):
                self.notify(
                    f"CloudFront behavior '{name}' TTL values must be integers",
                    severity="error",
                )
                return False
            if min_ttl < 0 or default_ttl < min_ttl or max_ttl < default_ttl:
                self.notify(
                    f"CloudFront behavior '{name}' has invalid TTL ordering",
                    severity="error",
                )
                return False
            query_mode = str(behavior.get("query_strings", "all"))
            query_allowlist = list(behavior.get("query_string_allowlist", []))
            if query_mode == "allowlist" and not query_allowlist:
                self.notify(
                    f"CloudFront behavior '{name}' requires query allowlist",
                    severity="error",
                )
                return False
            if query_mode != "allowlist" and query_allowlist:
                self.notify(
                    f"CloudFront behavior '{name}' has query allowlist but mode is not allowlist",
                    severity="error",
                )
                return False
            cookie_mode = str(behavior.get("cookies", "none"))
            cookie_allowlist = list(behavior.get("cookie_allowlist", []))
            if cookie_mode == "allowlist" and not cookie_allowlist:
                self.notify(
                    f"CloudFront behavior '{name}' requires cookie allowlist",
                    severity="error",
                )
                return False
            if cookie_mode != "allowlist" and cookie_allowlist:
                self.notify(
                    f"CloudFront behavior '{name}' has cookie allowlist but mode is not allowlist",
                    severity="error",
                )
                return False

        return True

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_select_changed(self, _event: Select.Changed) -> None:
        self._capture_draft()

    def on_switch_changed(self, _event: Switch.Changed) -> None:
        self._capture_draft()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None:
            return
        if event.list_view.id == "path-rule-list":
            if idx >= len(self._path_rules):
                return
            self._editing_path_rule_index = idx
            rule = self._path_rules[idx]
            self.query_one("#path_rule_name", Input).value = rule.get("name", "")
            self.query_one("#path_rule_pattern", Input).value = rule.get(
                "path_pattern", ""
            )
            self.query_one("#path_rule_priority", Input).value = str(
                rule.get("priority", "")
            )
            target = rule.get("target_service")
            if target:
                self.query_one("#path_rule_target_service", Select).value = target
            return
        if event.list_view.id == "cloudfront-conn-list":
            if idx >= len(self._cloudfront_connections):
                return
            self._editing_cloudfront_conn_index = idx
            conn = self._cloudfront_connections[idx]
            self.query_one("#cloudfront_conn_env_key", Input).value = conn.get(
                "env_key", ""
            )
            service = conn.get("service")
            if service:
                self.query_one("#cloudfront_conn_service", Select).value = service
            return
        if event.list_view.id == "cloudfront-behavior-list":
            if idx >= len(self._cloudfront_cached_behaviors):
                return
            self._editing_cloudfront_behavior_index = idx
            behavior = self._cloudfront_cached_behaviors[idx]
            self.query_one("#cloudfront_behavior_name", Input).value = behavior.get(
                "name", ""
            )
            self.query_one("#cloudfront_behavior_path", Input).value = behavior.get(
                "path_pattern", ""
            )
            self.query_one("#cloudfront_behavior_query_mode", Select).value = (
                behavior.get("query_strings", "all")
            )
            self.query_one("#cloudfront_behavior_query_allowlist", Input).value = ", ".join(
                behavior.get("query_string_allowlist", [])
            )
            self.query_one("#cloudfront_behavior_cookie_mode", Select).value = (
                behavior.get("cookies", "none")
            )
            self.query_one("#cloudfront_behavior_cookie_allowlist", Input).value = ", ".join(
                behavior.get("cookie_allowlist", [])
            )
            self.query_one("#cloudfront_behavior_min_ttl", Input).value = str(
                behavior.get("min_ttl_seconds", 0)
            )
            self.query_one("#cloudfront_behavior_default_ttl", Input).value = str(
                behavior.get("default_ttl_seconds", 3600)
            )
            self.query_one("#cloudfront_behavior_max_ttl", Input).value = str(
                behavior.get("max_ttl_seconds", 31536000)
            )
            self.query_one("#cloudfront_behavior_compress", Switch).value = bool(
                behavior.get("compress", True)
            )
            self.query_one(
                "#cloudfront_behavior_cache_by_origin_headers", Switch
            ).value = bool(behavior.get("cache_by_origin_headers", True))
            self.query_one("#cloudfront_behavior_forward_auth", Switch).value = bool(
                behavior.get("forward_authorization_header", False)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            if self._persist_to_state():
                self.app.go_to_step(target)
            return
        if event.button.id == "back":
            self._state["_wizard_last_screen"] = "services"
            self.app.pop_screen()
        elif event.button.id == "next":
            if self._persist_to_state():
                self.app.advance_to("rds")
        elif event.button.id == "path_rule_add":
            self._add_path_rule()
            self._capture_draft()
        elif event.button.id == "path_rule_remove":
            self._remove_path_rule()
            self._capture_draft()
        elif event.button.id == "fetch_next_priority_default":
            self._start_fetch_next_priority(target="default")
        elif event.button.id == "fetch_next_priority_rule":
            self._start_fetch_next_priority(target="rule")
        elif event.button.id == "cloudfront_conn_add":
            self._add_cloudfront_connection()
            self._capture_draft()
        elif event.button.id == "cloudfront_conn_remove":
            self._remove_cloudfront_connection()
            self._capture_draft()
        elif event.button.id == "cloudfront_behavior_add":
            self._add_cloudfront_behavior()
            self._capture_draft()
        elif event.button.id == "cloudfront_behavior_remove":
            self._remove_cloudfront_behavior()
            self._capture_draft()
        elif event.button.id == "cloudfront_fetch_certificates":
            self._start_fetch_cloudfront_certificates()

    def before_step_navigation(self, _target: str) -> bool:
        return self._persist_to_state()

    def _clear_path_rule_form(self) -> None:
        self.query_one("#path_rule_name", Input).value = ""
        self.query_one("#path_rule_pattern", Input).value = ""
        self.query_one("#path_rule_priority", Input).value = ""
        self.query_one("#path_rule_target_service", Select).clear()
        self._editing_path_rule_index = None

    def _add_path_rule(self) -> None:
        name = self.query_one("#path_rule_name", Input).value.strip()
        path_pattern = self.query_one("#path_rule_pattern", Input).value.strip()
        target_raw = self.query_one("#path_rule_target_service", Select).value
        target = (
            str(target_raw).strip() if not self._is_select_empty(target_raw) else ""
        )
        priority_raw = self.query_one("#path_rule_priority", Input).value.strip()
        if not name or not path_pattern or not target or not priority_raw:
            self.notify(
                "Rule name, path pattern, target service, and priority are required",
                severity="error",
            )
            return
        try:
            priority = int(priority_raw)
        except ValueError:
            self.notify("Priority must be an integer", severity="error")
            return
        rule = {
            "name": name,
            "path_pattern": path_pattern,
            "target_service": target,
            "priority": priority,
        }
        if self._editing_path_rule_index is not None:
            self._path_rules[self._editing_path_rule_index] = rule
            self._editing_path_rule_index = None
        else:
            self._path_rules.append(rule)
        self._clear_path_rule_form()
        self._refresh_path_rule_sidebar()
        self.notify(f"Saved path rule '{name}'", severity="information")

    def _remove_path_rule(self) -> None:
        if self._editing_path_rule_index is None:
            return
        name = self._path_rules[self._editing_path_rule_index]["name"]
        del self._path_rules[self._editing_path_rule_index]
        self._clear_path_rule_form()
        self._refresh_path_rule_sidebar()
        self.notify(f"Removed path rule '{name}'", severity="information")

    def _clear_cloudfront_connection_form(self) -> None:
        self.query_one("#cloudfront_conn_env_key", Input).value = ""
        self.query_one("#cloudfront_conn_service", Select).clear()
        self._editing_cloudfront_conn_index = None

    def _add_cloudfront_connection(self) -> None:
        service_value = self.query_one("#cloudfront_conn_service", Select).value
        service = (
            str(service_value).strip()
            if not self._is_select_empty(service_value)
            else ""
        )
        env_key = self.query_one("#cloudfront_conn_env_key", Input).value.strip()
        if not service or not env_key:
            self.notify(
                "CloudFront connection requires service and env var key",
                severity="error",
            )
            return
        connection = {"service": service, "env_key": env_key}
        if self._editing_cloudfront_conn_index is not None:
            self._cloudfront_connections[self._editing_cloudfront_conn_index] = connection
            self._editing_cloudfront_conn_index = None
        else:
            self._cloudfront_connections.append(connection)
        self._clear_cloudfront_connection_form()
        self._refresh_cloudfront_connection_sidebar()
        self.notify("Saved CloudFront connection", severity="information")

    def _remove_cloudfront_connection(self) -> None:
        if self._editing_cloudfront_conn_index is None:
            return
        del self._cloudfront_connections[self._editing_cloudfront_conn_index]
        self._clear_cloudfront_connection_form()
        self._refresh_cloudfront_connection_sidebar()
        self.notify("Removed CloudFront connection", severity="information")

    @staticmethod
    def _parse_csv(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    def _clear_cloudfront_behavior_form(self) -> None:
        self.query_one("#cloudfront_behavior_name", Input).value = ""
        self.query_one("#cloudfront_behavior_path", Input).value = ""
        self.query_one("#cloudfront_behavior_query_mode", Select).value = "all"
        self.query_one("#cloudfront_behavior_query_allowlist", Input).value = ""
        self.query_one("#cloudfront_behavior_cookie_mode", Select).value = "none"
        self.query_one("#cloudfront_behavior_cookie_allowlist", Input).value = ""
        self.query_one("#cloudfront_behavior_min_ttl", Input).value = ""
        self.query_one("#cloudfront_behavior_default_ttl", Input).value = ""
        self.query_one("#cloudfront_behavior_max_ttl", Input).value = ""
        self.query_one("#cloudfront_behavior_compress", Switch).value = True
        self.query_one(
            "#cloudfront_behavior_cache_by_origin_headers", Switch
        ).value = True
        self.query_one("#cloudfront_behavior_forward_auth", Switch).value = False
        self._editing_cloudfront_behavior_index = None

    def _add_cloudfront_behavior(self) -> None:
        name = self.query_one("#cloudfront_behavior_name", Input).value.strip()
        path_pattern = self.query_one("#cloudfront_behavior_path", Input).value.strip()
        if not name or not path_pattern:
            self.notify(
                "CloudFront behavior requires name and path pattern",
                severity="error",
            )
            return
        try:
            min_ttl = int(
                self.query_one("#cloudfront_behavior_min_ttl", Input).value.strip()
                or "0"
            )
            default_ttl = int(
                self.query_one("#cloudfront_behavior_default_ttl", Input).value.strip()
                or "3600"
            )
            max_ttl = int(
                self.query_one("#cloudfront_behavior_max_ttl", Input).value.strip()
                or "31536000"
            )
        except ValueError:
            self.notify("CloudFront TTL values must be integers", severity="error")
            return

        query_mode_value = self.query_one("#cloudfront_behavior_query_mode", Select).value
        query_mode = (
            str(query_mode_value)
            if not self._is_select_empty(query_mode_value)
            else "all"
        )
        cookie_mode_value = self.query_one(
            "#cloudfront_behavior_cookie_mode", Select
        ).value
        cookie_mode = (
            str(cookie_mode_value)
            if not self._is_select_empty(cookie_mode_value)
            else "none"
        )

        behavior = {
            "name": name,
            "path_pattern": path_pattern,
            "compress": self.query_one("#cloudfront_behavior_compress", Switch).value,
            "cache_by_origin_headers": self.query_one(
                "#cloudfront_behavior_cache_by_origin_headers", Switch
            ).value,
            "min_ttl_seconds": min_ttl,
            "default_ttl_seconds": default_ttl,
            "max_ttl_seconds": max_ttl,
            "query_strings": query_mode,
            "query_string_allowlist": self._parse_csv(
                self.query_one("#cloudfront_behavior_query_allowlist", Input).value
            ),
            "cookies": cookie_mode,
            "cookie_allowlist": self._parse_csv(
                self.query_one("#cloudfront_behavior_cookie_allowlist", Input).value
            ),
            "forward_authorization_header": self.query_one(
                "#cloudfront_behavior_forward_auth", Switch
            ).value,
        }
        if self._editing_cloudfront_behavior_index is not None:
            self._cloudfront_cached_behaviors[self._editing_cloudfront_behavior_index] = (
                behavior
            )
            self._editing_cloudfront_behavior_index = None
        else:
            self._cloudfront_cached_behaviors.append(behavior)
        self._clear_cloudfront_behavior_form()
        self._refresh_cloudfront_behavior_sidebar()
        self.notify("Saved CloudFront cached behavior", severity="information")

    def _remove_cloudfront_behavior(self) -> None:
        if self._editing_cloudfront_behavior_index is None:
            return
        del self._cloudfront_cached_behaviors[self._editing_cloudfront_behavior_index]
        self._clear_cloudfront_behavior_form()
        self._refresh_cloudfront_behavior_sidebar()
        self.notify("Removed CloudFront cached behavior", severity="information")

    def _start_fetch_cloudfront_certificates(self) -> None:
        if self._cloudfront_certs_fetch_inflight:
            return
        self._cloudfront_certs_fetch_inflight = True
        self.query_one("#cloudfront_fetch_certificates", Button).disabled = True
        self.notify("Fetching ACM certificates from us-east-1...", severity="information")
        threading.Thread(
            target=self._fetch_cloudfront_certificates_worker,
            daemon=True,
        ).start()

    def _fetch_cloudfront_certificates_worker(self) -> None:
        try:
            acm = boto3.client("acm", region_name="us-east-1")
            paginator = acm.get_paginator("list_certificates")
            summaries: list[dict[str, object]] = []
            for page in paginator.paginate(CertificateStatuses=["ISSUED"]):
                summaries.extend(page.get("CertificateSummaryList", []))

            entries: list[tuple[str, str]] = []
            for summary in summaries:
                arn = str(summary.get("CertificateArn", "")).strip()
                domain = str(summary.get("DomainName", "")).strip() or "(no domain)"
                if not arn:
                    continue
                entries.append((f"{domain} [{arn}]", arn))

            entries.sort(key=lambda item: item[0].lower())
            self.app.call_from_thread(
                self._complete_fetch_cloudfront_certificates, entries, None
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(
                self._complete_fetch_cloudfront_certificates, [], str(exc)
            )

    def _complete_fetch_cloudfront_certificates(
        self,
        entries: list[tuple[str, str]],
        err: str | None,
    ) -> None:
        self._cloudfront_certs_fetch_inflight = False
        self.query_one("#cloudfront_fetch_certificates", Button).disabled = False
        if err:
            self.notify(f"Certificate lookup failed: {err}", severity="error")
            return
        self._cloudfront_cert_options = entries
        self._refresh_cloudfront_certificate_select()
        self._capture_draft()
        self.notify(
            f"Loaded {len(entries)} ACM certificate(s) from us-east-1",
            severity="information",
        )

    def _used_listener_priorities(self) -> set[int]:
        used = set()
        default_raw = self.query_one("#default_listener_priority", Input).value.strip()
        if default_raw:
            try:
                used.add(int(default_raw))
            except ValueError:
                pass
        for idx, rule in enumerate(self._path_rules):
            if idx == self._editing_path_rule_index:
                continue
            try:
                used.add(int(rule.get("priority", 0)))
            except (TypeError, ValueError):
                continue
        return used

    def _start_fetch_next_priority(self, *, target: str) -> None:
        if self._priority_fetch_inflight:
            return
        if target == "rule" and self._editing_path_rule_index is None:
            self.notify("Select a path rule first", severity="error")
            return
        self._priority_fetch_inflight = True
        self.query_one("#fetch_next_priority_default", Button).disabled = True
        self.query_one("#fetch_next_priority_rule", Button).disabled = True
        used = self._used_listener_priorities()
        region = str(self._state.get("aws_region", "us-east-1"))
        listener_arn = str(self._state.get("shared_listener_arn") or "").strip()
        alb_name = str(self._state.get("shared_alb_name") or "").strip()
        threading.Thread(
            target=self._fetch_next_priority_worker,
            args=(target, region, listener_arn, alb_name, used),
            daemon=True,
        ).start()

    def _fetch_next_priority_worker(
        self,
        target: str,
        region: str,
        listener_arn: str,
        alb_name: str,
        used: set[int],
    ) -> None:
        try:
            existing = set(used)
            elbv2 = boto3.client("elbv2", region_name=region)
            resolved_listener_arn = listener_arn
            if not resolved_listener_arn:
                if not alb_name:
                    raise RuntimeError(
                        "Set shared ALB name or shared listener ARN first"
                    )
                lbs = elbv2.describe_load_balancers(Names=[alb_name]).get(
                    "LoadBalancers", []
                )
                if len(lbs) != 1:
                    raise RuntimeError(
                        f"Expected one ALB named {alb_name}, found {len(lbs)}"
                    )
                listeners = elbv2.describe_listeners(
                    LoadBalancerArn=lbs[0]["LoadBalancerArn"]
                ).get("Listeners", [])
                preferred = next(
                    (
                        l
                        for l in listeners
                        if l.get("Protocol") == "HTTPS" and l.get("Port") == 443
                    ),
                    None,
                ) or next((l for l in listeners if l.get("Port") in {80, 443}), None)
                if not preferred:
                    raise RuntimeError("Could not find listener on ALB")
                resolved_listener_arn = preferred["ListenerArn"]
            paginator = elbv2.get_paginator("describe_rules")
            for page in paginator.paginate(ListenerArn=resolved_listener_arn):
                for rule in page.get("Rules", []):
                    p = rule.get("Priority")
                    if p and p != "default":
                        try:
                            existing.add(int(p))
                        except ValueError:
                            continue

            candidate = 50000
            while candidate > 0 and candidate in existing:
                candidate -= 1
            if candidate <= 0:
                raise RuntimeError(
                    "No available listener rule priorities in range 1-50000"
                )
            self.app.call_from_thread(
                self._complete_fetch_next_priority, target, candidate, None
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(
                self._complete_fetch_next_priority, target, None, str(exc)
            )

    def _complete_fetch_next_priority(
        self, target: str, priority: int | None, err: str | None
    ) -> None:
        self._priority_fetch_inflight = False
        self.query_one("#fetch_next_priority_default", Button).disabled = False
        self.query_one("#fetch_next_priority_rule", Button).disabled = False
        if err:
            self.notify(f"Priority lookup failed: {err}", severity="error")
            return
        if priority is None:
            return
        if target == "default":
            self.query_one("#default_listener_priority", Input).value = str(priority)
        else:
            self.query_one("#path_rule_priority", Input).value = str(priority)
        self._capture_draft()
        self.notify(f"Next available priority: {priority}", severity="information")
