"""ALB + routing configuration screen."""

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
    RadioButton,
    RadioSet,
    Select,
    Static,
)

from ..step_rail import StepRail


class AlbScreen(Screen):
    """Configure shared/dedicated ALB and cluster listener routing."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._alb_fetch_inflight = False
        self._priority_fetch_inflight = False
        self._path_rules: list[dict] = []
        self._editing_path_rule_index: int | None = None

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
                yield Static("ALB + Routing", classes="title")

                yield Label("ALB mode:", classes="section-label")
                with RadioSet(id="alb_mode"):
                    yield RadioButton(
                        "Shared (use existing ALB)",
                        id="alb_mode_shared",
                        value=True,
                    )
                    yield RadioButton(
                        "Dedicated (provision a new ALB)",
                        id="alb_mode_dedicated",
                    )

                with Vertical(id="alb_shared_fields"):
                    yield Label("Shared ALB name:", classes="section-label")
                    yield Input(placeholder="my-shared-alb", id="shared_alb_name")
                    yield Label("Shared listener ARN (optional):", classes="section-label")
                    yield Input(
                        placeholder="arn:aws:elasticloadbalancing:...",
                        id="shared_listener_arn",
                    )
                    yield Label(
                        "Shared ALB security group ID (optional):",
                        classes="section-label",
                    )
                    yield Input(placeholder="sg-0123456789abcdef0", id="shared_alb_sg_id")
                    yield Button(
                        "Fetch Shared ALB Details",
                        id="fetch_shared_alb",
                        variant="default",
                    )

                yield Label(
                    "ACM certificate ARN (required for dedicated HTTPS):",
                    classes="section-label",
                )
                yield Input(placeholder="arn:aws:acm:...", id="cert_arn")

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
                    yield Button("+ Add / Update Rule", id="path_rule_add", variant="success")
                    yield Button("Remove Rule", id="path_rule_remove", variant="error")
                yield Button(
                    "Get Next Available Priority",
                    id="fetch_next_priority_rule",
                    variant="default",
                )

    def on_mount(self) -> None:
        self._restore_from_draft()
        self._refresh_path_rule_sidebar()
        self._refresh_target_service_selects()
        self._toggle_alb_fields()

    def _restore_from_draft(self) -> None:
        draft = self._draft()
        mode = str(draft.get("alb_mode", self._state.get("alb_mode", "shared")))
        self.query_one(
            "#alb_mode_dedicated" if mode == "dedicated" else "#alb_mode_shared",
            RadioButton,
        ).value = True
        self.query_one("#shared_alb_name", Input).value = str(
            draft.get("shared_alb_name", self._state.get("shared_alb_name") or "")
        )
        self.query_one("#shared_listener_arn", Input).value = str(
            draft.get("shared_listener_arn", self._state.get("shared_listener_arn") or "")
        )
        self.query_one("#shared_alb_sg_id", Input).value = str(
            draft.get(
                "shared_alb_security_group_id",
                self._state.get("shared_alb_security_group_id") or "",
            )
        )
        self.query_one("#cert_arn", Input).value = str(
            draft.get("certificate_arn", self._state.get("certificate_arn") or "")
        )
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

    def _refresh_path_rule_sidebar(self) -> None:
        lv = self.query_one("#path-rule-list", ListView)
        lv.clear()
        for rule in self._path_rules:
            lv.append(
                ListItem(
                    Static(
                        f"{rule['name']}: {rule['path_pattern']} -> "
                        f"{rule['target_service']} ({rule['priority']})"
                    )
                )
            )

    def _refresh_target_service_selects(self) -> None:
        services = [s["name"] for s in self._state.get("services", []) if s.get("port")]
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
        elif not self._is_select_empty(current_rule_target) and current_rule_target in services:
            rule_select.value = current_rule_target
        else:
            rule_select.clear()

    def _toggle_alb_fields(self) -> None:
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        is_shared = not (alb_pressed and alb_pressed.id == "alb_mode_dedicated")
        self.query_one("#alb_shared_fields", Vertical).display = is_shared

    def _capture_draft(self) -> None:
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        mode = "dedicated" if alb_pressed and alb_pressed.id == "alb_mode_dedicated" else "shared"
        default_target = self.query_one("#default_target_service", Select).value
        path_target = self.query_one("#path_rule_target_service", Select).value
        self._draft().update(
            {
                "alb_mode": mode,
                "shared_alb_name": self.query_one("#shared_alb_name", Input).value,
                "shared_listener_arn": self.query_one("#shared_listener_arn", Input).value,
                "shared_alb_security_group_id": self.query_one("#shared_alb_sg_id", Input).value,
                "certificate_arn": self.query_one("#cert_arn", Input).value,
                "alb_domain": self.query_one("#alb_domain", Input).value,
                "default_target_service": (
                    str(default_target) if not self._is_select_empty(default_target) else None
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
                "path_rule_priority": self.query_one("#path_rule_priority", Input).value,
            }
        )

    def _persist_to_state(self) -> bool:
        if not self._validate_routing():
            return False
        self._capture_draft()
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        self._state["alb_mode"] = (
            "dedicated" if alb_pressed and alb_pressed.id == "alb_mode_dedicated" else "shared"
        )
        self._state["shared_alb_name"] = self.query_one("#shared_alb_name", Input).value.strip()
        self._state["shared_listener_arn"] = (
            self.query_one("#shared_listener_arn", Input).value.strip() or None
        )
        self._state["shared_alb_security_group_id"] = (
            self.query_one("#shared_alb_sg_id", Input).value.strip() or None
        )
        self._state["certificate_arn"] = self.query_one("#cert_arn", Input).value.strip() or None
        self._state["alb_domain"] = self.query_one("#alb_domain", Input).value.strip() or None
        default_target = self.query_one("#default_target_service", Select).value
        self._state["default_target_service"] = (
            str(default_target).strip() if not self._is_select_empty(default_target) else None
        )
        default_priority = self.query_one("#default_listener_priority", Input).value.strip()
        self._state["default_listener_priority"] = int(default_priority) if default_priority else None
        self._state["alb_path_rules"] = [dict(v) for v in self._path_rules]
        return True

    def _validate_routing(self) -> bool:
        domain = self.query_one("#alb_domain", Input).value.strip()
        target_value = self.query_one("#default_target_service", Select).value
        target = str(target_value).strip() if not self._is_select_empty(target_value) else None
        default_priority_raw = self.query_one("#default_listener_priority", Input).value.strip()
        if domain:
            if not target:
                self.notify("Default target service is required when cluster domain is set", severity="error")
                return False
            if not default_priority_raw:
                self.notify("Default listener priority is required when cluster domain is set", severity="error")
                return False
            try:
                default_priority = int(default_priority_raw)
            except ValueError:
                self.notify("Default listener priority must be an integer", severity="error")
                return False
            if default_priority < 1 or default_priority > 50000:
                self.notify("Default listener priority must be between 1 and 50000", severity="error")
                return False
        else:
            if target or default_priority_raw or self._path_rules:
                self.notify("Cluster domain is required when default/path routing is configured", severity="error")
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
                self.notify(f"Path rule '{name}' has an invalid priority", severity="error")
                return False
            if priority < 1 or priority > 50000:
                self.notify(f"Path rule '{name}' priority must be between 1 and 50000", severity="error")
                return False
            if priority in priorities:
                self.notify(f"Duplicate listener priority '{priority}' in routing rules", severity="error")
                return False
            priorities.add(priority)
        return True

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "alb_mode":
            self._toggle_alb_fields()
        self._capture_draft()

    def on_select_changed(self, _event: Select.Changed) -> None:
        self._capture_draft()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "path-rule-list":
            return
        idx = event.list_view.index
        if idx is None or idx >= len(self._path_rules):
            return
        self._editing_path_rule_index = idx
        rule = self._path_rules[idx]
        self.query_one("#path_rule_name", Input).value = rule.get("name", "")
        self.query_one("#path_rule_pattern", Input).value = rule.get("path_pattern", "")
        self.query_one("#path_rule_priority", Input).value = str(rule.get("priority", ""))
        target = rule.get("target_service")
        if target:
            self.query_one("#path_rule_target_service", Select).value = target

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
        elif event.button.id == "fetch_shared_alb":
            self._start_alb_fetch()
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
        target = str(target_raw).strip() if not self._is_select_empty(target_raw) else ""
        priority_raw = self.query_one("#path_rule_priority", Input).value.strip()
        if not name or not path_pattern or not target or not priority_raw:
            self.notify("Rule name, path pattern, target service, and priority are required", severity="error")
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
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        mode = "dedicated" if alb_pressed and alb_pressed.id == "alb_mode_dedicated" else "shared"
        region = str(self._state.get("aws_region", "us-east-1"))
        listener_arn = self.query_one("#shared_listener_arn", Input).value.strip()
        alb_name = self.query_one("#shared_alb_name", Input).value.strip()
        threading.Thread(
            target=self._fetch_next_priority_worker,
            args=(target, mode, region, listener_arn, alb_name, used),
            daemon=True,
        ).start()

    def _fetch_next_priority_worker(
        self,
        target: str,
        mode: str,
        region: str,
        listener_arn: str,
        alb_name: str,
        used: set[int],
    ) -> None:
        try:
            existing = set(used)
            if mode == "shared":
                elbv2 = boto3.client("elbv2", region_name=region)
                resolved_listener_arn = listener_arn
                if not resolved_listener_arn:
                    if not alb_name:
                        raise RuntimeError("Set shared ALB name or shared listener ARN first")
                    lbs = elbv2.describe_load_balancers(Names=[alb_name]).get("LoadBalancers", [])
                    if len(lbs) != 1:
                        raise RuntimeError(f"Expected one ALB named {alb_name}, found {len(lbs)}")
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
                raise RuntimeError("No available listener rule priorities in range 1-50000")
            self.app.call_from_thread(self._complete_fetch_next_priority, target, candidate, None)
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

    def _start_alb_fetch(self) -> None:
        if self._alb_fetch_inflight:
            return
        shared_alb_name = self.query_one("#shared_alb_name", Input).value.strip()
        if not shared_alb_name:
            self.notify("Set Shared ALB name first", severity="error")
            return
        self._alb_fetch_inflight = True
        self.query_one("#fetch_shared_alb", Button).disabled = True
        threading.Thread(
            target=self._fetch_shared_alb_worker,
            args=(str(self._state.get("aws_region", "us-east-1")), shared_alb_name),
            daemon=True,
        ).start()

    def _fetch_shared_alb_worker(self, aws_region: str, shared_alb_name: str) -> None:
        try:
            elbv2 = boto3.client("elbv2", region_name=aws_region)
            lbs = elbv2.describe_load_balancers(Names=[shared_alb_name]).get(
                "LoadBalancers", []
            )
            if len(lbs) != 1:
                raise RuntimeError(
                    f"Expected one ALB named {shared_alb_name}, found {len(lbs)}"
                )
            lb = lbs[0]
            alb_sg = lb["SecurityGroups"][0]
            listeners = elbv2.describe_listeners(
                LoadBalancerArn=lb["LoadBalancerArn"]
            ).get("Listeners", [])
            preferred = next(
                (
                    listener
                    for listener in listeners
                    if listener.get("Protocol") == "HTTPS" and listener.get("Port") == 443
                ),
                None,
            )
            if not preferred:
                preferred = next(
                    (
                        listener
                        for listener in listeners
                        if listener.get("Port") in {80, 443}
                    ),
                    None,
                )
            if not preferred:
                raise RuntimeError("Could not find listener on ALB")

            self.app.call_from_thread(
                self._alb_fetch_complete,
                preferred["ListenerArn"],
                alb_sg,
                None,
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(self._alb_fetch_complete, "", "", str(exc))

    def _alb_fetch_complete(
        self,
        shared_listener_arn: str,
        shared_alb_security_group_id: str,
        err: str | None,
    ) -> None:
        self._alb_fetch_inflight = False
        self.query_one("#fetch_shared_alb", Button).disabled = False
        if err:
            self.notify(f"AWS lookup failed: {err}", severity="error")
            return
        self.query_one("#shared_listener_arn", Input).value = shared_listener_arn
        self.query_one("#shared_alb_sg_id", Input).value = shared_alb_security_group_id
        self._capture_draft()
        self.notify("Fetched shared ALB values from AWS", severity="information")
