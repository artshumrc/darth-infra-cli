"""Welcome screen — project name, region, VPC, environments."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

from ..step_rail import StepRail


class WelcomeScreen(Screen):
    """First screen: basic project details."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def _draft(self) -> dict:
        d = self._state.setdefault("_wizard_draft", {})
        return d.setdefault("welcome", {})

    def compose(self) -> ComposeResult:
        draft = self._draft()
        with VerticalScroll(classes="form-container"):
            yield StepRail("welcome")
            yield Static("darth-infra — New Project Setup", classes="title")

            yield Label("Project name (kebab-case):", classes="section-label")
            yield Input(
                placeholder="my-webapp",
                id="project_name",
                value=draft.get("project_name", self._state.get("project_name", "")),
            )

            yield Label("AWS region:", classes="section-label")
            yield Input(
                placeholder="us-east-1",
                id="aws_region",
                value=draft.get("aws_region", self._state.get("aws_region", "us-east-1")),
            )

            yield Label("VPC name:", classes="section-label")
            yield Input(
                placeholder="artshumrc-prod-standard",
                id="vpc_name",
                value=draft.get(
                    "vpc_name", self._state.get("vpc_name", "artshumrc-prod-standard")
                ),
            )

            yield Label(
                "Environments (comma-separated, prod is always included):",
                classes="section-label",
            )
            yield Input(
                placeholder="prod, dev",
                id="environments",
                value=draft.get(
                    "environments",
                    ", ".join(self._state.get("environments", ["prod"])),
                ),
            )

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._draft().update(
            {
                "project_name": self.query_one("#project_name", Input).value,
                "aws_region": self.query_one("#aws_region", Input).value,
                "vpc_name": self.query_one("#vpc_name", Input).value,
                "environments": self.query_one("#environments", Input).value,
            }
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return

        if event.button.id == "next":
            if self._apply_form_to_state():
                self.app.advance_to("existing-resources")

    def _apply_form_to_state(self) -> bool:
        project_name = self.query_one("#project_name", Input).value.strip()
        if not project_name:
            self.notify("Project name is required", severity="error")
            return False

        self._state["project_name"] = project_name
        self._state["aws_region"] = (
            self.query_one("#aws_region", Input).value.strip() or "us-east-1"
        )
        self._state["vpc_name"] = (
            self.query_one("#vpc_name", Input).value.strip()
            or "artshumrc-prod-standard"
        )

        env_text = self.query_one("#environments", Input).value.strip()
        envs = [e.strip() for e in env_text.split(",") if e.strip()]
        if "prod" not in envs:
            envs.insert(0, "prod")
        self._state["environments"] = envs
        return True

    def before_step_navigation(self, target: str) -> bool:
        if target == "welcome":
            return True
        return self._apply_form_to_state()
