"""Welcome screen — project name, region, VPC, environments."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static


class WelcomeScreen(Screen):
    """First screen: basic project details."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield Static("darth-ecs — New Project Setup", classes="title")

            yield Label("Project name (kebab-case):", classes="section-label")
            yield Input(
                placeholder="my-webapp",
                id="project_name",
                value=self._state.get("project_name", ""),
            )

            yield Label("AWS region:", classes="section-label")
            yield Input(
                placeholder="us-east-1",
                id="aws_region",
                value=self._state.get("aws_region", "us-east-1"),
            )

            yield Label("VPC name:", classes="section-label")
            yield Input(
                placeholder="artshumrc-prod-standard",
                id="vpc_name",
                value=self._state.get("vpc_name", "artshumrc-prod-standard"),
            )

            yield Label(
                "Environments (comma-separated, prod is always included):",
                classes="section-label",
            )
            yield Input(
                placeholder="prod, dev",
                id="environments",
                value=", ".join(self._state.get("environments", ["prod"])),
            )

            with Vertical(classes="button-row"):
                yield Button("Next →", id="next", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            project_name = self.query_one("#project_name", Input).value.strip()
            if not project_name:
                self.notify("Project name is required", severity="error")
                return

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

            self.app.advance_to("services")
