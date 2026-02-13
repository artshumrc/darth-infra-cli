"""ALB configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static


class AlbScreen(Screen):
    """Configure ALB: shared or dedicated."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield Static("ALB Configuration", classes="title")

            yield Label("ALB mode:", classes="section-label")
            with RadioSet(id="alb_mode"):
                yield RadioButton(
                    "Shared (use an existing ALB)",
                    value=self._state.get("alb_mode") == "shared",
                    id="mode_shared",
                )
                yield RadioButton(
                    "Dedicated (provision a new ALB)",
                    value=self._state.get("alb_mode") == "dedicated",
                    id="mode_dedicated",
                )

            yield Label(
                "Shared ALB name:",
                classes="section-label",
            )
            yield Input(
                placeholder="my-shared-alb",
                id="shared_alb_name",
                value=self._state.get("shared_alb_name") or "",
            )

            yield Label(
                "ACM certificate ARN (required for dedicated HTTPS):",
                classes="section-label",
            )
            yield Input(
                placeholder="arn:aws:acm:...",
                id="cert_arn",
                value=self._state.get("certificate_arn") or "",
            )

            with Vertical(classes="button-row"):
                yield Button("← Back", id="back", variant="default")
                yield Button("Next →", id="next", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            radio_set = self.query_one("#alb_mode", RadioSet)
            pressed = radio_set.pressed_button
            if pressed and pressed.id == "mode_dedicated":
                self._state["alb_mode"] = "dedicated"
            else:
                self._state["alb_mode"] = "shared"

            self._state["shared_alb_name"] = self.query_one(
                "#shared_alb_name", Input
            ).value.strip()
            cert = self.query_one("#cert_arn", Input).value.strip() or None
            self._state["certificate_arn"] = cert

            self.app.advance_to("secrets")
