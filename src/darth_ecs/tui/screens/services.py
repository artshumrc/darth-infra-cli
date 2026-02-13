"""Services screen — add ECS services (name, Dockerfile, port, domain)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


class ServicesScreen(Screen):
    """Configure one or more ECS services."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_index: int | None = None

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

                yield Label("Command override (optional):", classes="section-label")
                yield Input(placeholder="", id="svc_command")

                with Vertical(classes="button-row"):
                    yield Button("← Back", id="back", variant="default")
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")
                    yield Button("Next →", id="next", variant="primary")

    def on_mount(self) -> None:
        self._refresh_sidebar()
        self._update_mode()

    def _refresh_sidebar(self) -> None:
        """Rebuild the sidebar list from current state."""
        lv = self.query_one("#item-list", ListView)
        lv.clear()
        for svc in self._state.get("services", []):
            lv.append(ListItem(Static(svc["name"])))

    def _update_mode(self) -> None:
        """Toggle button visibility based on add vs edit mode."""
        editing = self._editing_index is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Load a service into the form for editing."""
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
            self.query_one("#svc_command", Input).value = svc.get("command") or ""
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
        elif event.button.id == "next":
            name = self.query_one("#svc_name", Input).value.strip()
            if name and self._editing_index is None:
                self._add_service()
            if not self._state.get("services"):
                self.notify("Add at least one service", severity="error")
                return
            self.app.advance_to("rds")

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

        if port is not None and not domain:
            self.notify("Domain is required when port is set", severity="error")
            return None

        return {
            "name": name,
            "dockerfile": self.query_one("#svc_dockerfile", Input).value.strip()
            or "Dockerfile",
            "build_context": self.query_one("#svc_context", Input).value.strip() or ".",
            "port": port,
            "domain": domain,
            "health_check_path": self.query_one("#svc_health", Input).value.strip()
            or "/health",
            "command": command,
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
        self.query_one("#svc_command", Input).value = ""
        self._update_mode()
