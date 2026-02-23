"""Services screen — add ECS services and cluster-level ALB routing."""

from __future__ import annotations

import threading

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TextArea,
)

from ..step_rail import StepRail


class ServicesScreen(Screen):
    """Configure one or more ECS services."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_index: int | None = None
        self._ebs_volumes: list[dict] = []
        self._editing_ebs_index: int | None = None
        self._ulimits: list[dict] = []
        self._editing_ulimit_index: int | None = None
        self._env_vars: list[dict] = []
        self._editing_env_var_index: int | None = None
        self._active_section: str = "details"
        self._alb_fetch_inflight = False
        self._path_rules: list[dict] = []
        self._editing_path_rule_index: int | None = None
        self._priority_fetch_inflight = False

    def _draft(self) -> dict:
        d = self._state.setdefault("_wizard_draft", {})
        return d.setdefault("services", {})

    @staticmethod
    def _is_select_empty(value: object) -> bool:
        null_sentinel = getattr(Select, "NULL", object())
        blank_sentinel = getattr(Select, "BLANK", object())
        return value in {None, "", False, null_sentinel, blank_sentinel}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Added Services", classes="title")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield StepRail("services")
                yield Static("Service Details", classes="title")

                with Horizontal(classes="service-sub-rail"):
                    yield Button(
                        "Details",
                        id="service_tab_details",
                        variant="primary",
                        compact=True,
                    )
                    yield Button(
                        "Environment variables",
                        id="service_tab_env",
                        compact=True,
                    )
                    yield Button(
                        "Container Ulimits",
                        id="service_tab_ulimits",
                        compact=True,
                    )
                    yield Button(
                        "EBS Volumes",
                        id="service_tab_ebs",
                        compact=True,
                    )

                with Vertical(id="service_section_details", classes="service-section"):
                    yield Static("Service", classes="title")
                    yield Label("Service name:", classes="section-label")
                    yield Input(placeholder="django", id="svc_name")

                    yield Label("Dockerfile path:", classes="section-label")
                    yield Input(
                        placeholder="Dockerfile", id="svc_dockerfile", value="Dockerfile"
                    )

                    yield Label("Build context:", classes="section-label")
                    yield Input(placeholder=".", id="svc_context", value=".")

                    yield Label(
                        "External image (leave empty to build from Dockerfile):",
                        classes="section-label",
                    )
                    yield Input(
                        placeholder="docker.elastic.co/elasticsearch/elasticsearch:8.12.0",
                        id="svc_image",
                    )

                    yield Label(
                        "Container port (leave empty for workers):",
                        classes="section-label",
                    )
                    yield Input(placeholder="8000", id="svc_port", value="8000")

                    yield Label("Health check path:", classes="section-label")
                    yield Input(placeholder="/health", id="svc_health", value="/health")
                    yield Label("Health check success codes:", classes="section-label")
                    yield Input(
                        placeholder="200-399",
                        id="svc_health_codes",
                        value="200-399",
                    )
                    yield Label("Health check timeout (seconds):", classes="section-label")
                    yield Input(placeholder="5", id="svc_health_timeout", value="5")
                    yield Label("Health check interval (seconds):", classes="section-label")
                    yield Input(placeholder="30", id="svc_health_interval", value="30")
                    yield Label("Healthy threshold count:", classes="section-label")
                    yield Input(placeholder="5", id="svc_health_healthy", value="5")
                    yield Label("Unhealthy threshold count:", classes="section-label")
                    yield Input(placeholder="2", id="svc_health_unhealthy", value="2")
                    yield Label(
                        "ECS health check grace period (seconds, optional):",
                        classes="section-label",
                    )
                    yield Input(
                        placeholder="300",
                        id="svc_health_grace",
                    )

                    yield Label("CPU units:", classes="section-label")
                    yield Input(placeholder="256", id="svc_cpu", value="256")

                    yield Label("Memory (MiB):", classes="section-label")
                    yield Input(placeholder="512", id="svc_memory", value="512")

                    yield Label("Command override (optional):", classes="section-label")
                    yield Input(placeholder="", id="svc_command")

                    yield Checkbox(
                        "Enable service discovery (Cloud Map DNS)",
                        id="svc_discovery",
                    )

                    yield Label("Launch type:", classes="section-label")
                    with RadioSet(id="launch_type"):
                        yield RadioButton("Fargate", value=True, id="lt_fargate")
                        yield RadioButton("EC2", id="lt_ec2")

                    with Vertical(id="ec2_fields"):
                        yield Label("EC2 instance type:", classes="section-label")
                        yield Input(placeholder="t3.medium", id="svc_ec2_instance_type")

                        yield Label(
                            "User data script (optional):",
                            classes="section-label",
                        )
                        yield TextArea(
                            "",
                            id="svc_user_data_script_content",
                        )

                with Vertical(id="service_section_env", classes="service-section"):
                    yield Static("Environment Variables", classes="title")
                    yield ListView(id="env-var-list")

                    yield Label("Variable name:", classes="section-label")
                    yield Input(placeholder="DJANGO_SETTINGS_MODULE", id="env_var_key")

                    yield Label("Value:", classes="section-label")
                    yield Input(placeholder="myapp.settings.production", id="env_var_value")

                    with Horizontal(classes="button-row"):
                        yield Button("+ Add Env Var", id="env_var_add", variant="success")
                        yield Button("Remove Env Var", id="env_var_remove", variant="error")

                with Vertical(id="service_section_ulimits", classes="service-section"):
                    yield Static("Container Ulimits", classes="title")
                    yield ListView(id="ulimit-list")

                    yield Label("Ulimit name:", classes="section-label")
                    yield Input(placeholder="nofile", id="ulimit_name")

                    yield Label("Soft limit:", classes="section-label")
                    yield Input(placeholder="65536", id="ulimit_soft")

                    yield Label("Hard limit:", classes="section-label")
                    yield Input(placeholder="65536", id="ulimit_hard")

                    with Horizontal(classes="button-row"):
                        yield Button("+ Add Ulimit", id="ulimit_add", variant="success")
                        yield Button("Remove Ulimit", id="ulimit_remove", variant="error")

                with Vertical(id="service_section_ebs", classes="service-section"):
                    yield Static("EBS Volumes", classes="title")
                    yield ListView(id="ebs-list")

                    yield Label("Volume name:", classes="section-label")
                    yield Input(placeholder="data", id="ebs_name")

                    yield Label("Size (GiB):", classes="section-label")
                    yield Input(placeholder="50", id="ebs_size")

                    yield Label("Mount path:", classes="section-label")
                    yield Input(placeholder="/data", id="ebs_mount")

                    yield Label("Device name:", classes="section-label")
                    yield Input(
                        placeholder="/dev/xvdf",
                        id="ebs_device",
                        value="/dev/xvdf",
                    )

                    yield Label("Filesystem type:", classes="section-label")
                    yield Input(
                        placeholder="ext4",
                        id="ebs_fs_type",
                        value="ext4",
                    )

                    with Horizontal(classes="button-row"):
                        yield Button("+ Add Volume", id="ebs_add", variant="success")
                        yield Button("Remove Volume", id="ebs_remove", variant="error")

                with Vertical(classes="button-row"):
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")

    def on_mount(self) -> None:
        self._restore_from_draft()
        self._refresh_sidebar()
        self._update_mode()
        self._set_active_section("details")
        self._toggle_ec2_fields()
        self._refresh_ulimit_sidebar()
        self._refresh_env_var_sidebar()

    def _restore_from_draft(self) -> None:
        draft = self._draft()
        if self._state.get("services"):
            # Avoid stale seeded draft values overriding real service entries.
            draft = {}

        if draft.get("svc_name") is not None:
            self.query_one("#svc_name", Input).value = str(draft.get("svc_name", ""))
        if draft.get("svc_dockerfile") is not None:
            self.query_one("#svc_dockerfile", Input).value = str(
                draft.get("svc_dockerfile", "Dockerfile")
            )
        if draft.get("svc_context") is not None:
            self.query_one("#svc_context", Input).value = str(
                draft.get("svc_context", ".")
            )
        if draft.get("svc_image") is not None:
            self.query_one("#svc_image", Input).value = str(draft.get("svc_image", ""))
        if draft.get("svc_port") is not None:
            self.query_one("#svc_port", Input).value = str(draft.get("svc_port", ""))
        if draft.get("svc_health") is not None:
            self.query_one("#svc_health", Input).value = str(
                draft.get("svc_health", "/health")
            )
        if draft.get("svc_health_codes") is not None:
            self.query_one("#svc_health_codes", Input).value = str(
                draft.get("svc_health_codes", "200-399")
            )
        if draft.get("svc_health_timeout") is not None:
            self.query_one("#svc_health_timeout", Input).value = str(
                draft.get("svc_health_timeout", "5")
            )
        if draft.get("svc_health_interval") is not None:
            self.query_one("#svc_health_interval", Input).value = str(
                draft.get("svc_health_interval", "30")
            )
        if draft.get("svc_health_healthy") is not None:
            self.query_one("#svc_health_healthy", Input).value = str(
                draft.get("svc_health_healthy", "5")
            )
        if draft.get("svc_health_unhealthy") is not None:
            self.query_one("#svc_health_unhealthy", Input).value = str(
                draft.get("svc_health_unhealthy", "2")
            )
        if draft.get("svc_health_grace") is not None:
            self.query_one("#svc_health_grace", Input).value = str(
                draft.get("svc_health_grace", "")
            )
        if draft.get("svc_cpu") is not None:
            self.query_one("#svc_cpu", Input).value = str(draft.get("svc_cpu", "256"))
        if draft.get("svc_memory") is not None:
            self.query_one("#svc_memory", Input).value = str(
                draft.get("svc_memory", "512")
            )
        if draft.get("svc_command") is not None:
            self.query_one("#svc_command", Input).value = str(draft.get("svc_command", ""))
        if draft.get("svc_discovery") is not None:
            self.query_one("#svc_discovery", Checkbox).value = bool(
                draft.get("svc_discovery", False)
            )
        launch_type = draft.get("launch_type")
        if launch_type == "ec2":
            self._select_launch_type("ec2")
        elif launch_type == "fargate":
            self._select_launch_type("fargate")
        if draft.get("svc_ec2_instance_type") is not None:
            self.query_one("#svc_ec2_instance_type", Input).value = str(
                draft.get("svc_ec2_instance_type", "")
            )
        if draft.get("svc_user_data_script_content") is not None:
            self.query_one("#svc_user_data_script_content", TextArea).text = str(
                draft.get("svc_user_data_script_content", "")
            )
        if isinstance(draft.get("ebs_volumes"), list):
            self._ebs_volumes = [dict(v) for v in draft.get("ebs_volumes", [])]
            self._refresh_ebs_sidebar()
        if isinstance(draft.get("ulimits"), list):
            self._ulimits = [dict(v) for v in draft.get("ulimits", [])]
            self._refresh_ulimit_sidebar()
        if isinstance(draft.get("env_vars"), list):
            self._env_vars = [dict(v) for v in draft.get("env_vars", [])]
            self._refresh_env_var_sidebar()

    def _capture_draft(self) -> None:
        lt_set = self.query_one("#launch_type", RadioSet)
        lt_pressed = lt_set.pressed_button
        lt = "ec2" if lt_pressed and lt_pressed.id == "lt_ec2" else "fargate"
        self._draft().update(
            {
                "svc_name": self.query_one("#svc_name", Input).value,
                "svc_dockerfile": self.query_one("#svc_dockerfile", Input).value,
                "svc_context": self.query_one("#svc_context", Input).value,
                "svc_image": self.query_one("#svc_image", Input).value,
                "svc_port": self.query_one("#svc_port", Input).value,
                "svc_health": self.query_one("#svc_health", Input).value,
                "svc_health_codes": self.query_one("#svc_health_codes", Input).value,
                "svc_health_timeout": self.query_one("#svc_health_timeout", Input).value,
                "svc_health_interval": self.query_one("#svc_health_interval", Input).value,
                "svc_health_healthy": self.query_one("#svc_health_healthy", Input).value,
                "svc_health_unhealthy": self.query_one(
                    "#svc_health_unhealthy", Input
                ).value,
                "svc_health_grace": self.query_one("#svc_health_grace", Input).value,
                "svc_cpu": self.query_one("#svc_cpu", Input).value,
                "svc_memory": self.query_one("#svc_memory", Input).value,
                "svc_command": self.query_one("#svc_command", Input).value,
                "svc_discovery": self.query_one("#svc_discovery", Checkbox).value,
                "launch_type": lt,
                "svc_ec2_instance_type": self.query_one(
                    "#svc_ec2_instance_type", Input
                ).value,
                "svc_user_data_script_content": self.query_one(
                    "#svc_user_data_script_content", TextArea
                ).text,
                "ebs_name": self.query_one("#ebs_name", Input).value,
                "ebs_size": self.query_one("#ebs_size", Input).value,
                "ebs_mount": self.query_one("#ebs_mount", Input).value,
                "ebs_device": self.query_one("#ebs_device", Input).value,
                "ebs_fs_type": self.query_one("#ebs_fs_type", Input).value,
                "ulimit_name": self.query_one("#ulimit_name", Input).value,
                "ulimit_soft": self.query_one("#ulimit_soft", Input).value,
                "ulimit_hard": self.query_one("#ulimit_hard", Input).value,
                "env_var_key": self.query_one("#env_var_key", Input).value,
                "env_var_value": self.query_one("#env_var_value", Input).value,
                "ebs_volumes": [dict(v) for v in self._ebs_volumes],
                "ulimits": [dict(v) for v in self._ulimits],
                "env_vars": [dict(v) for v in self._env_vars],
            }
        )

    def _refresh_sidebar(self) -> None:
        """Rebuild the sidebar list from current state."""
        lv = self.query_one("#item-list", ListView)
        lv.clear()
        for svc in self._state.get("services", []):
            label = svc["name"]
            if svc.get("launch_type") == "ec2":
                label += " [EC2]"
            lv.append(ListItem(Static(label)))
        # Keep the form in add mode after list refresh; user can explicitly select to edit.
        lv.index = None

    def _refresh_ebs_sidebar(self) -> None:
        """Rebuild the EBS volume list."""
        lv = self.query_one("#ebs-list", ListView)
        lv.clear()
        for vol in self._ebs_volumes:
            lv.append(
                ListItem(
                    Static(f"{vol['name']} ({vol['size_gb']}G → {vol['mount_path']})")
                )
            )

    def _refresh_ulimit_sidebar(self) -> None:
        """Rebuild the ulimit list."""
        lv = self.query_one("#ulimit-list", ListView)
        lv.clear()
        for ul in self._ulimits:
            lv.append(
                ListItem(
                    Static(
                        f"{ul['name']} (soft={ul['soft_limit']}, hard={ul['hard_limit']})"
                    )
                )
            )

    def _refresh_env_var_sidebar(self) -> None:
        """Rebuild the environment variable list."""
        lv = self.query_one("#env-var-list", ListView)
        lv.clear()
        for ev in self._env_vars:
            lv.append(ListItem(Static(f"{ev['key']}={ev['value']}")))

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

    def _refresh_routing_service_selects(self) -> None:
        services = [
            svc["name"] for svc in self._state.get("services", []) if svc.get("port")
        ]
        options = [(svc, svc) for svc in services]

        default_select = self.query_one("#default_target_service", Select)
        current_default = default_select.value
        default_select.set_options(options)
        if not self._is_select_empty(current_default) and any(
            svc == current_default for svc in services
        ):
            default_select.value = current_default
        else:
            default_select.clear()

        rule_select = self.query_one("#path_rule_target_service", Select)
        current_rule_target = rule_select.value
        rule_select.set_options(options)
        if not self._is_select_empty(current_rule_target) and any(
            svc == current_rule_target for svc in services
        ):
            rule_select.value = current_rule_target
        else:
            rule_select.clear()

    def _toggle_ec2_fields(self) -> None:
        """Show or hide EC2-specific fields and EC2-only tabs."""
        lt_set = self.query_one("#launch_type", RadioSet)
        lt_pressed = lt_set.pressed_button
        is_ec2 = bool(lt_pressed and lt_pressed.id == "lt_ec2")
        ec2_container = self.query_one("#ec2_fields", Vertical)
        ec2_container.display = is_ec2
        if is_ec2 and not self.query_one("#svc_ec2_instance_type", Input).value.strip():
            self.query_one("#svc_ec2_instance_type", Input).value = "t3.medium"
        self.query_one("#service_tab_ulimits", Button).disabled = not is_ec2
        self.query_one("#service_tab_ebs", Button).disabled = not is_ec2
        if not is_ec2 and self._active_section in {"ulimits", "ebs"}:
            self._set_active_section("details")
        else:
            self._set_active_section(self._active_section)

    def _toggle_alb_fields(self) -> None:
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        is_shared = not (alb_pressed and alb_pressed.id == "alb_mode_dedicated")
        self.query_one("#alb_shared_fields", Vertical).display = is_shared

    def _select_launch_type(self, launch_type: str) -> None:
        target = self.query_one(
            "#lt_ec2" if launch_type == "ec2" else "#lt_fargate",
            RadioButton,
        )
        if not target.value:
            target.value = True

    def _select_alb_mode(self, mode: str) -> None:
        target = self.query_one(
            "#alb_mode_dedicated" if mode == "dedicated" else "#alb_mode_shared",
            RadioButton,
        )
        if not target.value:
            target.value = True

    def _persist_alb_to_state(self) -> None:
        alb_set = self.query_one("#alb_mode", RadioSet)
        alb_pressed = alb_set.pressed_button
        mode = "dedicated" if alb_pressed and alb_pressed.id == "alb_mode_dedicated" else "shared"
        self._state["alb_mode"] = mode
        self._state["shared_alb_name"] = self.query_one(
            "#shared_alb_name", Input
        ).value.strip()
        self._state["shared_listener_arn"] = (
            self.query_one("#shared_listener_arn", Input).value.strip() or None
        )
        self._state["shared_alb_security_group_id"] = (
            self.query_one("#shared_alb_sg_id", Input).value.strip() or None
        )
        self._state["certificate_arn"] = (
            self.query_one("#cert_arn", Input).value.strip() or None
        )
        self._state["alb_domain"] = self.query_one("#alb_domain", Input).value.strip() or None
        default_target = self.query_one("#default_target_service", Select).value
        self._state["default_target_service"] = (
            str(default_target).strip()
            if not self._is_select_empty(default_target)
            else None
        )
        priority = self.query_one("#default_listener_priority", Input).value.strip()
        if priority:
            try:
                self._state["default_listener_priority"] = int(priority)
            except ValueError:
                self._state["default_listener_priority"] = None
        else:
            self._state["default_listener_priority"] = None
        self._state["alb_path_rules"] = [dict(rule) for rule in self._path_rules]

    def _set_active_section(self, section: str) -> None:
        allowed = {"details", "env", "ulimits", "ebs"}
        if section not in allowed:
            return

        self._active_section = section
        self.query_one("#service_section_details", Vertical).display = section == "details"
        self.query_one("#service_section_env", Vertical).display = section == "env"
        self.query_one("#service_section_ulimits", Vertical).display = section == "ulimits"
        self.query_one("#service_section_ebs", Vertical).display = section == "ebs"

        self.query_one("#service_tab_details", Button).variant = (
            "primary" if section == "details" else "default"
        )
        self.query_one("#service_tab_env", Button).variant = (
            "primary" if section == "env" else "default"
        )
        self.query_one("#service_tab_ulimits", Button).variant = (
            "primary" if section == "ulimits" else "default"
        )
        self.query_one("#service_tab_ebs", Button).variant = (
            "primary" if section == "ebs" else "default"
        )

    def _update_mode(self) -> None:
        """Toggle button visibility based on add vs edit mode."""
        editing = self._editing_index is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "launch_type":
            self._toggle_ec2_fields()
        self._capture_draft()

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._capture_draft()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        self._capture_draft()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Load a service into the form for editing."""
        if event.list_view.id == "ebs-list":
            idx = event.list_view.index
            if idx is not None and idx < len(self._ebs_volumes):
                self._editing_ebs_index = idx
                vol = self._ebs_volumes[idx]
                self.query_one("#ebs_name", Input).value = vol.get("name", "")
                self.query_one("#ebs_size", Input).value = str(vol.get("size_gb", ""))
                self.query_one("#ebs_mount", Input).value = vol.get("mount_path", "")
                self.query_one("#ebs_device", Input).value = vol.get(
                    "device_name", "/dev/xvdf"
                )
                self.query_one("#ebs_fs_type", Input).value = vol.get(
                    "filesystem_type", "ext4"
                )
            return

        if event.list_view.id == "ulimit-list":
            idx = event.list_view.index
            if idx is not None and idx < len(self._ulimits):
                self._editing_ulimit_index = idx
                ul = self._ulimits[idx]
                self.query_one("#ulimit_name", Input).value = ul.get("name", "")
                self.query_one("#ulimit_soft", Input).value = str(
                    ul.get("soft_limit", "")
                )
                self.query_one("#ulimit_hard", Input).value = str(
                    ul.get("hard_limit", "")
                )
            return

        if event.list_view.id == "env-var-list":
            idx = event.list_view.index
            if idx is not None and idx < len(self._env_vars):
                self._editing_env_var_index = idx
                ev = self._env_vars[idx]
                self.query_one("#env_var_key", Input).value = ev.get("key", "")
                self.query_one("#env_var_value", Input).value = ev.get("value", "")
            return

        idx = event.list_view.index
        services = self._state.get("services", [])
        if idx is not None and idx < len(services):
            self._editing_index = idx
            self._set_active_section("details")
            svc = services[idx]
            self.query_one("#svc_name", Input).value = svc.get("name", "")
            self.query_one("#svc_dockerfile", Input).value = svc.get(
                "dockerfile", "Dockerfile"
            )
            self.query_one("#svc_context", Input).value = svc.get("build_context", ".")
            self.query_one("#svc_port", Input).value = (
                str(svc["port"]) if svc.get("port") else ""
            )
            self.query_one("#svc_health", Input).value = svc.get(
                "health_check_path", "/health"
            )
            self.query_one("#svc_health_codes", Input).value = svc.get(
                "health_check_http_codes", "200-399"
            )
            self.query_one("#svc_health_timeout", Input).value = str(
                svc.get("health_check_timeout_seconds", 5)
            )
            self.query_one("#svc_health_interval", Input).value = str(
                svc.get("health_check_interval_seconds", 30)
            )
            self.query_one("#svc_health_healthy", Input).value = str(
                svc.get("healthy_threshold_count", 5)
            )
            self.query_one("#svc_health_unhealthy", Input).value = str(
                svc.get("unhealthy_threshold_count", 2)
            )
            self.query_one("#svc_health_grace", Input).value = (
                str(svc.get("health_check_grace_period_seconds"))
                if svc.get("health_check_grace_period_seconds") is not None
                else ""
            )
            self.query_one("#svc_cpu", Input).value = str(svc.get("cpu", 256))
            self.query_one("#svc_memory", Input).value = str(svc.get("memory_mib", 512))
            self.query_one("#svc_command", Input).value = svc.get("command") or ""
            self.query_one("#svc_image", Input).value = svc.get("image") or ""

            # Service discovery
            self.query_one("#svc_discovery", Checkbox).value = svc.get(
                "enable_service_discovery", False
            )

            # Launch type
            is_ec2 = svc.get("launch_type") == "ec2"
            self._select_launch_type("ec2" if is_ec2 else "fargate")
            self._toggle_ec2_fields()

            # EC2 fields
            self.query_one("#svc_ec2_instance_type", Input).value = (
                svc.get("ec2_instance_type") or ""
            )
            self.query_one("#svc_user_data_script_content", TextArea).text = (
                svc.get("user_data_script_content") or ""
            )

            # EBS volumes
            self._ebs_volumes = [dict(v) for v in svc.get("ebs_volumes", [])]
            self._editing_ebs_index = None
            self._refresh_ebs_sidebar()

            # Ulimits
            self._ulimits = [dict(u) for u in svc.get("ulimits", [])]
            self._editing_ulimit_index = None
            self._refresh_ulimit_sidebar()

            # Environment variables
            env_vars_dict = svc.get("environment_variables", {})
            self._env_vars = [{"key": k, "value": v} for k, v in env_vars_dict.items()]
            self._editing_env_var_index = None
            self._refresh_env_var_sidebar()

            self._update_mode()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("service_tab_"):
            target = event.button.id.replace("service_tab_", "", 1)
            self._set_active_section(target)
            return

        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return

        if event.button.id == "back":
            self._capture_draft()
            self._state["_wizard_last_screen"] = "existing-resources"
            self.app.pop_screen()
        elif event.button.id == "add":
            if self._add_service():
                self._capture_draft()
        elif event.button.id == "save":
            if self._save_service():
                self._capture_draft()
        elif event.button.id == "remove":
            self._remove_service()
            self._capture_draft()
        elif event.button.id == "ebs_add":
            self._add_ebs_volume()
            self._capture_draft()
        elif event.button.id == "ebs_remove":
            self._remove_ebs_volume()
            self._capture_draft()
        elif event.button.id == "ulimit_add":
            self._add_ulimit()
            self._capture_draft()
        elif event.button.id == "ulimit_remove":
            self._remove_ulimit()
            self._capture_draft()
        elif event.button.id == "env_var_add":
            self._add_env_var()
            self._capture_draft()
        elif event.button.id == "env_var_remove":
            self._remove_env_var()
            self._capture_draft()
        elif event.button.id == "next":
            if self._persist_services_for_navigation(require_non_empty=True):
                self.app.advance_to("alb")

    def _persist_services_for_navigation(self, *, require_non_empty: bool) -> bool:
        self._capture_draft()
        name = self.query_one("#svc_name", Input).value.strip()
        if self._editing_index is not None:
            if not self._save_service():
                return False
        elif name:
            if not self._add_service():
                return False
        if require_non_empty and not self._state.get("services"):
            self.notify("Add at least one service", severity="error")
            return False
        return True

    def before_step_navigation(self, target: str) -> bool:
        require_non_empty = target not in {"welcome", "existing-resources"}
        return self._persist_services_for_navigation(require_non_empty=require_non_empty)

    def _start_alb_fetch(self) -> None:
        if self._alb_fetch_inflight:
            return

        shared_alb_name = self.query_one("#shared_alb_name", Input).value.strip()
        if not shared_alb_name:
            self.notify("Set Shared ALB name first", severity="error")
            return

        aws_region = str(self._state.get("aws_region", "us-east-1"))
        self._alb_fetch_inflight = True
        self.query_one("#fetch_shared_alb", Button).disabled = True
        self.notify("Fetching shared ALB details from AWS...")
        thread = threading.Thread(
            target=self._fetch_shared_alb_worker,
            args=(aws_region, shared_alb_name),
            daemon=True,
        )
        thread.start()

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
        self._persist_alb_to_state()
        self.notify("Fetched shared ALB values from AWS", severity="information")

    def _add_ebs_volume(self) -> None:
        """Add an EBS volume to the current service being edited."""
        name = self.query_one("#ebs_name", Input).value.strip()
        size_str = self.query_one("#ebs_size", Input).value.strip()
        mount = self.query_one("#ebs_mount", Input).value.strip()
        device = self.query_one("#ebs_device", Input).value.strip() or "/dev/xvdf"

        if not name or not size_str or not mount:
            self.notify(
                "Volume name, size, and mount path are required", severity="error"
            )
            return

        try:
            size_gb = int(size_str)
        except ValueError:
            self.notify("Size must be an integer", severity="error")
            return

        vol = {
            "name": name,
            "size_gb": size_gb,
            "mount_path": mount,
            "device_name": device,
            "volume_type": "gp3",
            "filesystem_type": self.query_one("#ebs_fs_type", Input).value.strip()
            or "ext4",
        }

        if self._editing_ebs_index is not None:
            self._ebs_volumes[self._editing_ebs_index] = vol
            self._editing_ebs_index = None
        else:
            self._ebs_volumes.append(vol)

        self._clear_ebs_form()
        self._refresh_ebs_sidebar()
        self.notify(f"Added EBS volume '{name}'")

    def _remove_ebs_volume(self) -> None:
        """Remove the selected EBS volume."""
        if self._editing_ebs_index is not None:
            name = self._ebs_volumes[self._editing_ebs_index]["name"]
            del self._ebs_volumes[self._editing_ebs_index]
            self._editing_ebs_index = None
            self._clear_ebs_form()
            self._refresh_ebs_sidebar()
            self.notify(f"Removed EBS volume '{name}'")

    def _clear_ebs_form(self) -> None:
        """Reset EBS volume form fields."""
        self.query_one("#ebs_name", Input).value = ""
        self.query_one("#ebs_size", Input).value = ""
        self.query_one("#ebs_mount", Input).value = ""
        self.query_one("#ebs_device", Input).value = "/dev/xvdf"
        self.query_one("#ebs_fs_type", Input).value = "ext4"
        self._editing_ebs_index = None

    def _add_ulimit(self) -> None:
        """Add a ulimit to the current service being edited."""
        name = self.query_one("#ulimit_name", Input).value.strip()
        soft_str = self.query_one("#ulimit_soft", Input).value.strip()
        hard_str = self.query_one("#ulimit_hard", Input).value.strip()

        if not name or not soft_str or not hard_str:
            self.notify(
                "Ulimit name, soft limit, and hard limit are required",
                severity="error",
            )
            return

        try:
            soft_limit = int(soft_str)
            hard_limit = int(hard_str)
        except ValueError:
            self.notify("Limits must be integers", severity="error")
            return

        ul = {
            "name": name,
            "soft_limit": soft_limit,
            "hard_limit": hard_limit,
        }

        if self._editing_ulimit_index is not None:
            self._ulimits[self._editing_ulimit_index] = ul
            self._editing_ulimit_index = None
        else:
            self._ulimits.append(ul)

        self._clear_ulimit_form()
        self._refresh_ulimit_sidebar()
        self.notify(f"Added ulimit '{name}'")

    def _remove_ulimit(self) -> None:
        """Remove the selected ulimit."""
        if self._editing_ulimit_index is not None:
            name = self._ulimits[self._editing_ulimit_index]["name"]
            del self._ulimits[self._editing_ulimit_index]
            self._editing_ulimit_index = None
            self._clear_ulimit_form()
            self._refresh_ulimit_sidebar()
            self.notify(f"Removed ulimit '{name}'")

    def _clear_ulimit_form(self) -> None:
        """Reset ulimit form fields."""
        self.query_one("#ulimit_name", Input).value = ""
        self.query_one("#ulimit_soft", Input).value = ""
        self.query_one("#ulimit_hard", Input).value = ""
        self._editing_ulimit_index = None

    def _add_env_var(self) -> None:
        """Add an environment variable to the current service."""
        key = self.query_one("#env_var_key", Input).value.strip()
        value = self.query_one("#env_var_value", Input).value.strip()

        if not key:
            self.notify("Variable name is required", severity="error")
            return

        ev = {"key": key, "value": value}

        if self._editing_env_var_index is not None:
            self._env_vars[self._editing_env_var_index] = ev
            self._editing_env_var_index = None
        else:
            # Prevent duplicate keys
            for existing in self._env_vars:
                if existing["key"] == key:
                    self.notify(
                        f"Variable '{key}' already exists — select it to edit",
                        severity="error",
                    )
                    return
            self._env_vars.append(ev)

        self._clear_env_var_form()
        self._refresh_env_var_sidebar()
        self.notify(f"Added env var '{key}'")

    def _remove_env_var(self) -> None:
        """Remove the selected environment variable."""
        if self._editing_env_var_index is not None:
            key = self._env_vars[self._editing_env_var_index]["key"]
            del self._env_vars[self._editing_env_var_index]
            self._editing_env_var_index = None
            self._clear_env_var_form()
            self._refresh_env_var_sidebar()
            self.notify(f"Removed env var '{key}'")

    def _clear_env_var_form(self) -> None:
        """Reset environment variable form fields."""
        self.query_one("#env_var_key", Input).value = ""
        self.query_one("#env_var_value", Input).value = ""
        self._editing_env_var_index = None

    def _add_path_rule(self) -> None:
        name = self.query_one("#path_rule_name", Input).value.strip()
        path_pattern = self.query_one("#path_rule_pattern", Input).value.strip()
        target_raw = self.query_one("#path_rule_target_service", Select).value
        target = str(target_raw).strip() if not self._is_select_empty(target_raw) else ""
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
        if priority < 1 or priority > 50000:
            self.notify("Priority must be between 1 and 50000", severity="error")
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
        self._editing_path_rule_index = None
        self._clear_path_rule_form()
        self._refresh_path_rule_sidebar()
        self.notify(f"Removed path rule '{name}'", severity="information")

    def _clear_path_rule_form(self) -> None:
        self.query_one("#path_rule_name", Input).value = ""
        self.query_one("#path_rule_pattern", Input).value = ""
        self.query_one("#path_rule_target_service", Select).clear()
        self.query_one("#path_rule_priority", Input).value = ""
        self._editing_path_rule_index = None

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
        used = self._used_listener_priorities()
        aws_region = str(self._state.get("aws_region", "us-east-1"))
        mode = str(self._state.get("alb_mode", "shared"))
        shared_listener_arn = self.query_one("#shared_listener_arn", Input).value.strip()
        shared_alb_name = self.query_one("#shared_alb_name", Input).value.strip()

        self._priority_fetch_inflight = True
        self.query_one("#fetch_next_priority_rule", Button).disabled = True
        self.query_one("#fetch_next_priority_default", Button).disabled = True
        threading.Thread(
            target=self._fetch_next_priority_worker,
            args=(target, mode, aws_region, shared_listener_arn, shared_alb_name, used),
            daemon=True,
        ).start()

    def _fetch_next_priority_worker(
        self,
        target: str,
        mode: str,
        aws_region: str,
        shared_listener_arn: str,
        shared_alb_name: str,
        used: set[int],
    ) -> None:
        try:
            existing = set(used)
            if mode == "shared":
                listener_arn = shared_listener_arn
                elbv2 = boto3.client("elbv2", region_name=aws_region)
                if not listener_arn:
                    if not shared_alb_name:
                        raise RuntimeError(
                            "Set shared ALB name or shared listener ARN before fetching"
                        )
                    lbs = elbv2.describe_load_balancers(Names=[shared_alb_name]).get(
                        "LoadBalancers", []
                    )
                    if len(lbs) != 1:
                        raise RuntimeError(
                            f"Expected one ALB named {shared_alb_name}, found {len(lbs)}"
                        )
                    listeners = elbv2.describe_listeners(
                        LoadBalancerArn=lbs[0]["LoadBalancerArn"]
                    ).get("Listeners", [])
                    preferred = next(
                        (
                            listener
                            for listener in listeners
                            if listener.get("Protocol") == "HTTPS"
                            and listener.get("Port") == 443
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
                    listener_arn = preferred["ListenerArn"]

                paginator = elbv2.get_paginator("describe_rules")
                for page in paginator.paginate(ListenerArn=listener_arn):
                    for rule in page.get("Rules", []):
                        priority = rule.get("Priority")
                        if priority and priority != "default":
                            try:
                                existing.add(int(priority))
                            except ValueError:
                                continue

            candidate = 1
            while candidate in existing:
                candidate += 1
            self.app.call_from_thread(
                self._complete_fetch_next_priority, target, candidate, None
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(
                self._complete_fetch_next_priority, target, None, str(exc)
            )

    def _complete_fetch_next_priority(
        self,
        target: str,
        priority: int | None,
        err: str | None,
    ) -> None:
        self._priority_fetch_inflight = False
        self.query_one("#fetch_next_priority_rule", Button).disabled = False
        self.query_one("#fetch_next_priority_default", Button).disabled = False
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

    def _read_form(self) -> dict | None:
        """Read and validate the form fields."""
        name = self.query_one("#svc_name", Input).value.strip()
        if not name:
            self.notify("Service name is required", severity="error")
            return None

        port_str = self.query_one("#svc_port", Input).value.strip()
        if port_str:
            try:
                port = int(port_str)
            except ValueError:
                self.notify("Container port must be an integer", severity="error")
                return None
        else:
            port = None
        command = self.query_one("#svc_command", Input).value.strip() or None
        image = self.query_one("#svc_image", Input).value.strip() or None

        cpu_str = self.query_one("#svc_cpu", Input).value.strip()
        try:
            cpu = int(cpu_str) if cpu_str else 256
        except ValueError:
            self.notify("CPU must be an integer", severity="error")
            return None

        memory_str = self.query_one("#svc_memory", Input).value.strip()
        try:
            memory_mib = int(memory_str) if memory_str else 512
        except ValueError:
            self.notify("Memory must be an integer", severity="error")
            return None
        timeout_str = self.query_one("#svc_health_timeout", Input).value.strip()
        interval_str = self.query_one("#svc_health_interval", Input).value.strip()
        healthy_str = self.query_one("#svc_health_healthy", Input).value.strip()
        unhealthy_str = self.query_one("#svc_health_unhealthy", Input).value.strip()
        grace_str = self.query_one("#svc_health_grace", Input).value.strip()
        try:
            health_check_timeout_seconds = int(timeout_str) if timeout_str else 5
            health_check_interval_seconds = int(interval_str) if interval_str else 30
            healthy_threshold_count = int(healthy_str) if healthy_str else 5
            unhealthy_threshold_count = int(unhealthy_str) if unhealthy_str else 2
            health_check_grace_period_seconds = (
                int(grace_str) if grace_str else None
            )
        except ValueError:
            self.notify("Health check timing values must be integers", severity="error")
            return None
        if not (2 <= health_check_timeout_seconds <= 120):
            self.notify("Health check timeout must be between 2 and 120", severity="error")
            return None
        if not (5 <= health_check_interval_seconds <= 300):
            self.notify("Health check interval must be between 5 and 300", severity="error")
            return None
        if not (2 <= healthy_threshold_count <= 10):
            self.notify("Healthy threshold must be between 2 and 10", severity="error")
            return None
        if not (2 <= unhealthy_threshold_count <= 10):
            self.notify("Unhealthy threshold must be between 2 and 10", severity="error")
            return None
        if health_check_grace_period_seconds is not None and not (
            0 <= health_check_grace_period_seconds <= 7200
        ):
            self.notify("Health check grace must be between 0 and 7200", severity="error")
            return None

        # Launch type
        is_ec2 = self.query_one("#lt_ec2", RadioButton).value
        launch_type = "ec2" if is_ec2 else "fargate"

        ec2_instance_type = None
        user_data_script_content = None
        ebs_volumes: list[dict] = []

        if is_ec2:
            ec2_instance_type = (
                self.query_one("#svc_ec2_instance_type", Input).value.strip() or None
            )
            if not ec2_instance_type:
                self.notify(
                    "EC2 instance type is required for EC2 launch type",
                    severity="error",
                )
                return None
            user_data_script_content = (
                self.query_one("#svc_user_data_script_content", TextArea).text.strip()
                or None
            )
            ebs_volumes = list(self._ebs_volumes)

        ulimits = list(self._ulimits)

        environment_variables = {ev["key"]: ev["value"] for ev in self._env_vars}

        return {
            "name": name,
            "dockerfile": self.query_one("#svc_dockerfile", Input).value.strip()
            or "Dockerfile",
            "build_context": self.query_one("#svc_context", Input).value.strip() or ".",
            "image": image,
            "port": port,
            "health_check_path": self.query_one("#svc_health", Input).value.strip()
            or "/health",
            "health_check_http_codes": self.query_one(
                "#svc_health_codes", Input
            ).value.strip()
            or "200-399",
            "health_check_timeout_seconds": health_check_timeout_seconds,
            "health_check_interval_seconds": health_check_interval_seconds,
            "healthy_threshold_count": healthy_threshold_count,
            "unhealthy_threshold_count": unhealthy_threshold_count,
            "health_check_grace_period_seconds": health_check_grace_period_seconds,
            "cpu": cpu,
            "memory_mib": memory_mib,
            "command": command,
            "enable_service_discovery": self.query_one(
                "#svc_discovery", Checkbox
            ).value,
            "launch_type": launch_type,
            "ec2_instance_type": ec2_instance_type,
            "user_data_script": None,
            "user_data_script_content": user_data_script_content,
            "ebs_volumes": ebs_volumes,
            "ulimits": ulimits,
            "environment_variables": environment_variables,
        }

    def _add_service(self) -> bool:
        svc = self._read_form()
        if svc is None:
            return False
        self._state.setdefault("services", []).append(svc)
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Added service '{svc['name']}'")
        return True

    def _save_service(self) -> bool:
        if self._editing_index is None:
            return False
        svc = self._read_form()
        if svc is None:
            return False
        self._state["services"][self._editing_index] = svc
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Updated service '{svc['name']}'")
        return True

    def _remove_service(self) -> None:
        if self._editing_index is None:
            return
        name = self._state["services"][self._editing_index]["name"]
        del self._state["services"][self._editing_index]
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Removed service '{name}'")

    def _clear_form(self) -> None:
        """Reset form to add mode."""
        self._editing_index = None
        self.query_one("#svc_name", Input).value = ""
        self.query_one("#svc_dockerfile", Input).value = "Dockerfile"
        self.query_one("#svc_context", Input).value = "."
        self.query_one("#svc_port", Input).value = "8000"
        self.query_one("#svc_health", Input).value = "/health"
        self.query_one("#svc_health_codes", Input).value = "200-399"
        self.query_one("#svc_health_timeout", Input).value = "5"
        self.query_one("#svc_health_interval", Input).value = "30"
        self.query_one("#svc_health_healthy", Input).value = "5"
        self.query_one("#svc_health_unhealthy", Input).value = "2"
        self.query_one("#svc_health_grace", Input).value = ""
        self.query_one("#svc_cpu", Input).value = "256"
        self.query_one("#svc_memory", Input).value = "512"
        self.query_one("#svc_command", Input).value = ""
        self.query_one("#svc_image", Input).value = ""
        self._select_launch_type("fargate")
        self.query_one("#svc_discovery", Checkbox).value = False
        self.query_one("#svc_ec2_instance_type", Input).value = ""
        self.query_one("#svc_user_data_script_content", TextArea).text = ""
        self._ebs_volumes = []
        self._editing_ebs_index = None
        self._clear_ebs_form()
        self._refresh_ebs_sidebar()
        self._ulimits = []
        self._editing_ulimit_index = None
        self._clear_ulimit_form()
        self._refresh_ulimit_sidebar()
        self._env_vars = []
        self._editing_env_var_index = None
        self._clear_env_var_form()
        self._refresh_env_var_sidebar()
        self._toggle_ec2_fields()
        self._update_mode()
