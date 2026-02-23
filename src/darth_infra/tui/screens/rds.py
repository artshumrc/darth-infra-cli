"""RDS configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, Switch

from ..step_rail import StepRail
from ..steps import STEP_ORDER


class RdsScreen(Screen):
    """Optional: configure an RDS PostgreSQL instance."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def _draft(self) -> dict:
        d = self._state.setdefault("_wizard_draft", {})
        return d.setdefault("rds", {})

    def compose(self) -> ComposeResult:
        draft = self._draft()
        rds = self._state.get("rds") or {}
        with VerticalScroll(classes="form-container"):
            yield StepRail("rds")
            yield Static("RDS Database (Optional)", classes="title")

            yield Label("Enable RDS PostgreSQL?", classes="section-label")
            yield Switch(
                id="enable_rds",
                value=bool(draft.get("enable_rds", bool(self._state.get("rds")))),
            )

            yield Label("Database name:", classes="section-label")
            yield Input(
                placeholder="myapp",
                id="db_name",
                value=str(draft.get("db_name", rds.get("database_name", ""))),
            )

            yield Label("Instance type:", classes="section-label")
            yield Input(
                placeholder="t4g.micro",
                id="db_instance",
                value=str(draft.get("db_instance", rds.get("instance_type", "t4g.micro"))),
            )

            yield Label("Storage (GB):", classes="section-label")
            yield Input(
                placeholder="20",
                id="db_storage",
                value=str(
                    draft.get(
                        "db_storage",
                        rds.get("allocated_storage_gb", 20),
                    )
                ),
            )

            yield Label(
                "Expose to services (comma-separated):",
                classes="section-label",
            )
            svc_names = ", ".join(s["name"] for s in self._state.get("services", []))
            yield Input(
                placeholder=svc_names,
                id="db_expose",
                value=str(draft.get("db_expose", ", ".join(rds.get("expose_to", [])) or svc_names)),
            )

    def _capture_draft(self) -> None:
        self._draft().update(
            {
                "enable_rds": self.query_one("#enable_rds", Switch).value,
                "db_name": self.query_one("#db_name", Input).value,
                "db_instance": self.query_one("#db_instance", Input).value,
                "db_storage": self.query_one("#db_storage", Input).value,
                "db_expose": self.query_one("#db_expose", Input).value,
            }
        )

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_switch_changed(self, _event: Switch.Changed) -> None:
        self._capture_draft()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return
        if event.button.id == "back":
            self._state["_wizard_last_screen"] = "alb"
            self.app.pop_screen()
        elif event.button.id == "next":
            if self._apply_to_state():
                self.app.advance_to("s3")

    def _apply_to_state(self) -> bool:
        self._capture_draft()
        enabled = self.query_one("#enable_rds", Switch).value
        if enabled:
            db_name = self.query_one("#db_name", Input).value.strip()
            if not db_name:
                self.notify("Database name is required", severity="error")
                return False

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
        return True

    def before_step_navigation(self, target: str) -> bool:
        current_index = STEP_ORDER.index("rds")
        target_index = STEP_ORDER.index(target) if target in STEP_ORDER else current_index
        if target_index <= current_index:
            self._capture_draft()
            return True
        return self._apply_to_state()
