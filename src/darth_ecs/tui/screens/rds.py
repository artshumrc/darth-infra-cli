"""RDS configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, Switch


class RdsScreen(Screen):
    """Optional: configure an RDS PostgreSQL instance."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield Static("RDS Database (Optional)", classes="title")

            yield Label("Enable RDS PostgreSQL?", classes="section-label")
            yield Switch(id="enable_rds", value=False)

            yield Label("Database name:", classes="section-label")
            yield Input(placeholder="myapp", id="db_name")

            yield Label("Instance type:", classes="section-label")
            yield Input(placeholder="t4g.micro", id="db_instance", value="t4g.micro")

            yield Label("Storage (GB):", classes="section-label")
            yield Input(placeholder="20", id="db_storage", value="20")

            yield Label(
                "Expose to services (comma-separated):",
                classes="section-label",
            )
            svc_names = ", ".join(s["name"] for s in self._state.get("services", []))
            yield Input(placeholder=svc_names, id="db_expose", value=svc_names)

            with Vertical(classes="button-row"):
                yield Button("← Back", id="back", variant="default")
                yield Button("Next →", id="next", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            enabled = self.query_one("#enable_rds", Switch).value
            if enabled:
                db_name = self.query_one("#db_name", Input).value.strip()
                if not db_name:
                    self.notify("Database name is required", severity="error")
                    return

                expose_text = self.query_one("#db_expose", Input).value.strip()
                expose_to = [e.strip() for e in expose_text.split(",") if e.strip()]

                self._state["rds"] = {
                    "database_name": db_name,
                    "instance_type": self.query_one("#db_instance", Input).value.strip()
                    or "t4g.micro",
                    "allocated_storage_gb": int(
                        self.query_one("#db_storage", Input).value.strip() or "20"
                    ),
                    "expose_to": expose_to,
                }
            else:
                self._state["rds"] = None

            self.app.advance_to("s3")
