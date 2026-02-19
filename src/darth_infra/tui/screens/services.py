"""Services screen — add ECS services (name, Dockerfile, port, domain, launch type)."""

from __future__ import annotations

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
    Static,
)


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

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Added Services", classes="title")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield Static("Service Details", classes="title")

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

                yield Label(
                    "Domain (required if port is set):", classes="section-label"
                )
                yield Input(placeholder="myapp.example.com", id="svc_domain")

                yield Label("Health check path:", classes="section-label")
                yield Input(placeholder="/health", id="svc_health", value="/health")

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

                # --- Launch type selection ---
                yield Label("Launch type:", classes="section-label")
                with RadioSet(id="launch_type"):
                    yield RadioButton("Fargate", value=True, id="lt_fargate")
                    yield RadioButton("EC2", id="lt_ec2")

                # --- EC2-specific fields (conditionally visible) ---
                with Vertical(id="ec2_fields"):
                    yield Label("EC2 instance type:", classes="section-label")
                    yield Input(placeholder="t3.medium", id="svc_ec2_instance_type")

                    yield Label(
                        "User data script path (optional):",
                        classes="section-label",
                    )
                    yield Input(
                        placeholder="scripts/setup.sh",
                        id="svc_user_data_script",
                    )

                    # --- Ulimits sub-section ---
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
                        yield Button(
                            "Remove Ulimit", id="ulimit_remove", variant="error"
                        )

                    # --- EBS volumes sub-section ---
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
                    yield Button("← Back", id="back", variant="default")
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")
                    yield Button("Next →", id="next", variant="primary")

    def on_mount(self) -> None:
        self._refresh_sidebar()
        self._update_mode()
        self._toggle_ec2_fields()
        self._refresh_ulimit_sidebar()

    def _refresh_sidebar(self) -> None:
        """Rebuild the sidebar list from current state."""
        lv = self.query_one("#item-list", ListView)
        lv.clear()
        for svc in self._state.get("services", []):
            label = svc["name"]
            if svc.get("launch_type") == "ec2":
                label += " [EC2]"
            lv.append(ListItem(Static(label)))

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

    def _toggle_ec2_fields(self) -> None:
        """Show or hide EC2-specific fields based on launch type selection."""
        is_ec2 = self.query_one("#lt_ec2", RadioButton).value
        ec2_container = self.query_one("#ec2_fields", Vertical)
        ec2_container.display = is_ec2

    def _update_mode(self) -> None:
        """Toggle button visibility based on add vs edit mode."""
        editing = self._editing_index is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """React to launch type radio change."""
        if event.radio_set.id == "launch_type":
            self._toggle_ec2_fields()

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

        idx = event.list_view.index
        services = self._state.get("services", [])
        if idx is not None and idx < len(services):
            self._editing_index = idx
            svc = services[idx]
            self.query_one("#svc_name", Input).value = svc.get("name", "")
            self.query_one("#svc_dockerfile", Input).value = svc.get(
                "dockerfile", "Dockerfile"
            )
            self.query_one("#svc_context", Input).value = svc.get("build_context", ".")
            self.query_one("#svc_port", Input).value = (
                str(svc["port"]) if svc.get("port") else ""
            )
            self.query_one("#svc_domain", Input).value = svc.get("domain") or ""
            self.query_one("#svc_health", Input).value = svc.get(
                "health_check_path", "/health"
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
            self.query_one("#lt_fargate", RadioButton).value = not is_ec2
            self.query_one("#lt_ec2", RadioButton).value = is_ec2
            self._toggle_ec2_fields()

            # EC2 fields
            self.query_one("#svc_ec2_instance_type", Input).value = (
                svc.get("ec2_instance_type") or ""
            )
            self.query_one("#svc_user_data_script", Input).value = (
                svc.get("user_data_script") or ""
            )

            # EBS volumes
            self._ebs_volumes = [dict(v) for v in svc.get("ebs_volumes", [])]
            self._editing_ebs_index = None
            self._refresh_ebs_sidebar()

            # Ulimits
            self._ulimits = [dict(u) for u in svc.get("ulimits", [])]
            self._editing_ulimit_index = None
            self._refresh_ulimit_sidebar()

            self._update_mode()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "add":
            self._add_service()
        elif event.button.id == "save":
            self._save_service()
        elif event.button.id == "remove":
            self._remove_service()
        elif event.button.id == "ebs_add":
            self._add_ebs_volume()
        elif event.button.id == "ebs_remove":
            self._remove_ebs_volume()
        elif event.button.id == "ulimit_add":
            self._add_ulimit()
        elif event.button.id == "ulimit_remove":
            self._remove_ulimit()
        elif event.button.id == "next":
            name = self.query_one("#svc_name", Input).value.strip()
            if name and self._editing_index is None:
                self._add_service()
            if not self._state.get("services"):
                self.notify("Add at least one service", severity="error")
                return
            self.app.advance_to("rds")

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

    def _read_form(self) -> dict | None:
        """Read and validate the form fields."""
        name = self.query_one("#svc_name", Input).value.strip()
        if not name:
            self.notify("Service name is required", severity="error")
            return None

        port_str = self.query_one("#svc_port", Input).value.strip()
        port = int(port_str) if port_str else None
        domain = self.query_one("#svc_domain", Input).value.strip() or None
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

        # Launch type
        is_ec2 = self.query_one("#lt_ec2", RadioButton).value
        launch_type = "ec2" if is_ec2 else "fargate"

        ec2_instance_type = None
        user_data_script = None
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
            user_data_script = (
                self.query_one("#svc_user_data_script", Input).value.strip() or None
            )
            ebs_volumes = list(self._ebs_volumes)

        ulimits = list(self._ulimits)

        return {
            "name": name,
            "dockerfile": self.query_one("#svc_dockerfile", Input).value.strip()
            or "Dockerfile",
            "build_context": self.query_one("#svc_context", Input).value.strip() or ".",
            "image": image,
            "port": port,
            "domain": domain,
            "health_check_path": self.query_one("#svc_health", Input).value.strip()
            or "/health",
            "cpu": cpu,
            "memory_mib": memory_mib,
            "command": command,
            "enable_service_discovery": self.query_one(
                "#svc_discovery", Checkbox
            ).value,
            "launch_type": launch_type,
            "ec2_instance_type": ec2_instance_type,
            "user_data_script": user_data_script,
            "ebs_volumes": ebs_volumes,
            "ulimits": ulimits,
        }

    def _add_service(self) -> None:
        svc = self._read_form()
        if svc is None:
            return
        self._state.setdefault("services", []).append(svc)
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Added service '{svc['name']}'")

    def _save_service(self) -> None:
        if self._editing_index is None:
            return
        svc = self._read_form()
        if svc is None:
            return
        self._state["services"][self._editing_index] = svc
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Updated service '{svc['name']}'")

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
        self.query_one("#svc_domain", Input).value = ""
        self.query_one("#svc_health", Input).value = "/health"
        self.query_one("#svc_cpu", Input).value = "256"
        self.query_one("#svc_memory", Input).value = "512"
        self.query_one("#svc_command", Input).value = ""
        self.query_one("#svc_image", Input).value = ""
        self.query_one("#lt_fargate", RadioButton).value = True
        self.query_one("#lt_ec2", RadioButton).value = False
        self.query_one("#svc_discovery", Checkbox).value = False
        self.query_one("#svc_ec2_instance_type", Input).value = ""
        self.query_one("#svc_user_data_script", Input).value = ""
        self._ebs_volumes = []
        self._editing_ebs_index = None
        self._clear_ebs_form()
        self._refresh_ebs_sidebar()
        self._ulimits = []
        self._editing_ulimit_index = None
        self._clear_ulimit_form()
        self._refresh_ulimit_sidebar()
        self._toggle_ec2_fields()
        self._update_mode()
