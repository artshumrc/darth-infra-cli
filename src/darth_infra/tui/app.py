"""Textual TUI application for ``darth-infra init``."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from pathlib import Path

from ..config.models import ProjectConfig
from .steps import STEP_ORDER
from .wizard_export import merge_seed_state, save_wizard_export
from .screens.welcome import WelcomeScreen
from .screens.existing_resources import ExistingResourcesScreen
from .screens.services import ServicesScreen
from .screens.alb import AlbScreen
from .screens.rds import RdsScreen
from .screens.s3 import S3Screen
from .screens.secrets import SecretsScreen
from .screens.review import ReviewScreen


class DarthEcsInitApp(App[None]):
    """Interactive setup wizard for darth-infra projects."""

    CSS = """
    Screen {
        align: center middle;
    }
    .screen-layout {
        width: 100%;
        max-width: 120;
        height: 100%;
        max-height: 100%;
    }
    .sidebar {
        width: 30;
        height: 100%;
        border: round $accent;
        padding: 1;
    }
    .sidebar #item-list {
        height: 1fr;
    }
    #env-var-list {
        height: 6;
        min-height: 6;
    }
    .form-container {
        width: 80;
        max-height: 100%;
        height: auto;
        border: round $accent;
        padding: 1 2;
    }
    .step-rail {
        layout: vertical;
        width: 1fr;
        height: auto;
        align: center middle;
        margin-bottom: 1;
    }
    .step-row {
        layout: horizontal;
        width: 1fr;
        height: auto;
        align: center middle;
    }
    .step-rail Button {
        margin: 0 1 0 0;
        min-width: 7;
    }
    .screen-layout .form-container {
        width: 1fr;
    }
    .title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .section-label {
        text-style: bold;
        margin-top: 1;
    }
    Button {
        margin: 1 0;
    }
    .button-row {
        layout: horizontal;
        height: auto;
        align: center middle;
    }
    .service-sub-rail {
        layout: horizontal;
        height: auto;
        width: 1fr;
        align: left middle;
        margin-bottom: 1;
    }
    .service-sub-rail Button {
        margin: 0 1 0 0;
        min-width: 12;
    }
    .service-section {
        height: auto;
        width: 1fr;
    }
    Input {
        margin-bottom: 1;
    }
    #svc_user_data_script_content {
        height: 10;
        margin-bottom: 1;
    }
    #ec2_fields {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "next_step", "Next Step", show=True),
        Binding("p", "prev_step", "Prev Step", show=True),
    ]

    def __init__(
        self,
        *,
        seed_state: dict | None = None,
        wizard_export_path: str | None = None,
    ) -> None:
        super().__init__()
        self.result_config: ProjectConfig | None = None
        self._completed = False
        self._wizard_export_path = wizard_export_path
        self._state: dict = merge_seed_state(seed_state)
        self._state.setdefault("_wizard_last_screen", "welcome")
        self._state.setdefault("_wizard_draft", {})
        self._state.setdefault("_wizard_max_step_index", 0)

    def on_mount(self) -> None:
        start = self._state.get("_wizard_last_screen", "welcome")
        if start not in STEP_ORDER:
            start = "welcome"

        self.push_screen(WelcomeScreen(self._state))
        if start != "welcome":
            target_index = STEP_ORDER.index(start)
            self._state["_wizard_max_step_index"] = max(
                int(self._state.get("_wizard_max_step_index", 0)),
                target_index,
            )
            for step in STEP_ORDER[1 : target_index + 1]:
                self.advance_to(step)

    def advance_to(self, screen_name: str) -> None:
        """Navigate to the next screen in the wizard."""
        screens = {
            "existing-resources": ExistingResourcesScreen,
            "services": ServicesScreen,
            "alb": AlbScreen,
            "rds": RdsScreen,
            "s3": S3Screen,
            "secrets": SecretsScreen,
            "review": ReviewScreen,
        }
        if screen_name in screens:
            self._state["_wizard_last_screen"] = screen_name
            self._state["_wizard_max_step_index"] = max(
                int(self._state.get("_wizard_max_step_index", 0)),
                STEP_ORDER.index(screen_name),
            )
            self.push_screen(screens[screen_name](self._state))

    def go_to_step(self, screen_name: str) -> None:
        """Navigate to an arbitrary step while preserving stack semantics."""
        if screen_name not in STEP_ORDER:
            return

        current_screen = self.screen
        before_nav = getattr(current_screen, "before_step_navigation", None)
        if callable(before_nav):
            should_continue = before_nav(screen_name)
            if should_continue is False:
                return

        current = str(self._state.get("_wizard_last_screen", "welcome"))
        if current not in STEP_ORDER:
            current = "welcome"

        if current == screen_name:
            return

        current_index = STEP_ORDER.index(current)
        target_index = STEP_ORDER.index(screen_name)
        max_step_index = int(self._state.get("_wizard_max_step_index", current_index))

        if target_index > current_index:
            if target_index > max_step_index + 1:
                target_index = max_step_index + 1
            for step in STEP_ORDER[current_index + 1 : target_index + 1]:
                self.advance_to(step)
            return

        for _ in range(current_index - target_index):
            self.pop_screen()
        self._state["_wizard_last_screen"] = screen_name

    def finish(self, config: ProjectConfig) -> None:
        """Complete the wizard with a final config."""
        self._completed = True
        self.result_config = config
        self._save_export()
        self.exit()

    def action_quit(self) -> None:
        """Persist current draft and exit the wizard."""
        self._save_export()
        self.exit()

    def action_next_step(self) -> None:
        current = str(self._state.get("_wizard_last_screen", "welcome"))
        if current not in STEP_ORDER:
            return
        idx = STEP_ORDER.index(current)
        if idx < len(STEP_ORDER) - 1:
            self.go_to_step(STEP_ORDER[idx + 1])

    def action_prev_step(self) -> None:
        current = str(self._state.get("_wizard_last_screen", "welcome"))
        if current not in STEP_ORDER:
            return
        idx = STEP_ORDER.index(current)
        if idx > 0:
            self.go_to_step(STEP_ORDER[idx - 1])

    def _save_export(self) -> None:
        path = self._wizard_export_path
        if not path:
            return
        current_screen = self.screen
        # Best-effort flush of in-progress widget state into app state before export.
        for hook_name in ("_capture_draft", "_persist_to_state", "_persist_for_navigation"):
            hook = getattr(current_screen, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    # Export should never fail because a screen-specific draft hook errored.
                    pass
        save_wizard_export(
            Path(path),
            state=self._state,
            completed=self._completed,
            last_screen=str(self._state.get("_wizard_last_screen", "welcome")),
        )
