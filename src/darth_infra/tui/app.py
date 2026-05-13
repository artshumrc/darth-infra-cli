"""Textual TUI application for ``darth-infra tui``."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..config.loader import CONFIG_FILENAME, dump_config, find_config, load_config
from ..config.models import ProjectConfig
from .steps import STEP_ORDER
from .wizard_export import merge_seed_state, project_config_to_wizard_state
from .screens.welcome import WelcomeScreen
from .screens.existing_resources import ExistingResourcesScreen
from .screens.services import ServicesScreen
from .screens.alb import AlbScreen
from .screens.rds import RdsScreen
from .screens.s3 import S3Screen
from .screens.secrets import SecretsScreen
from .screens.tags import TagsScreen
from .screens.review import ReviewScreen, build_config_from_state


class QuitSaveConfirmScreen(ModalScreen[str]):
    """Modal prompt shown when wizard changes differ from darth-infra.toml."""

    DEFAULT_CSS = """
    QuitSaveConfirmScreen {
        align: center middle;
    }
    QuitSaveConfirmScreen > Vertical {
        width: 72;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    QuitSaveConfirmScreen .button-row {
        layout: horizontal;
        align: center middle;
        margin-top: 1;
        height: auto;
    }
    QuitSaveConfirmScreen Button {
        margin: 0 1;
        min-width: 14;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Save changes to darth-infra.toml before exit?", classes="title"
            )
            yield Static(
                "The current wizard values differ from the existing darth-infra.toml."
            )
            with Vertical(classes="button-row"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Disregard", id="disregard")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or "cancel"
        if button_id not in {"save", "disregard", "cancel"}:
            button_id = "cancel"
        self.dismiss(button_id)


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
    #conn-list {
        height: 7;
        min-height: 7;
    }
    #sec_existing_list,
    #sec_existing_selection {
        height: 10;
        min-height: 10;
    }
    .section-divider {
        color: $text-muted;
        margin: 1 0;
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
    ) -> None:
        super().__init__()
        self.result_config: ProjectConfig | None = None
        self._state: dict = merge_seed_state(seed_state)
        self._state.setdefault("_wizard_last_screen", "welcome")
        self._state.setdefault("_wizard_draft", {})
        self._state.setdefault("_wizard_max_step_index", 0)
        try:
            self._config_path = find_config(Path.cwd())
        except FileNotFoundError:
            self._config_path = Path.cwd() / CONFIG_FILENAME
        self._pending_quit_toml: str | None = None

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
            self._state["_wizard_transit_target"] = start
            try:
                for step in STEP_ORDER[1 : target_index + 1]:
                    self.advance_to(step)
            finally:
                self._state.pop("_wizard_transit_target", None)

    def advance_to(self, screen_name: str) -> None:
        """Navigate to the next screen in the wizard."""
        screens = {
            "existing-resources": ExistingResourcesScreen,
            "services": ServicesScreen,
            "alb": AlbScreen,
            "rds": RdsScreen,
            "s3": S3Screen,
            "secrets": SecretsScreen,
            "tags": TagsScreen,
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
            target_step = STEP_ORDER[target_index]
            if target_index > current_index + 1:
                self._state["_wizard_transit_target"] = target_step
            try:
                for step in STEP_ORDER[current_index + 1 : target_index + 1]:
                    self.advance_to(step)
            finally:
                self._state.pop("_wizard_transit_target", None)
            return

        for _ in range(current_index - target_index):
            self.pop_screen()
        self._state["_wizard_last_screen"] = screen_name

    def finish(self, config: ProjectConfig) -> None:
        """Complete the wizard with a final config."""
        self.result_config = config
        self.exit()

    def action_quit(self) -> None:
        """Optionally persist confirmed changes to darth-infra.toml, then exit."""
        self._flush_current_screen_state()

        try:
            candidate = build_config_from_state(self._state)
        except Exception:
            self.exit()
            return

        candidate_toml = dump_config(candidate)
        current_toml = ""
        if self._config_path.is_file():
            try:
                existing_config = load_config(self._config_path)
                existing_tui_state = project_config_to_wizard_state(existing_config)
                existing_tui_config = build_config_from_state(existing_tui_state)
                if candidate == existing_tui_config:
                    self.exit()
                    return
            except Exception:
                pass
            current_toml = self._config_path.read_text()

        if candidate_toml == current_toml:
            self.exit()
            return

        self._pending_quit_toml = candidate_toml
        self.push_screen(QuitSaveConfirmScreen(), self._handle_quit_choice)

    def _handle_quit_choice(self, choice: str | None) -> None:
        if choice == "save" and self._pending_quit_toml is not None:
            self._config_path.write_text(self._pending_quit_toml)
            self.notify(f"Saved {self._config_path.name}", severity="information")
            self._pending_quit_toml = None
            self.exit()
            return
        if choice == "save":
            self._pending_quit_toml = None
            self.exit()
            return
        if choice == "disregard":
            self._pending_quit_toml = None
            self.exit()
            return
        self._pending_quit_toml = None

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

    def _flush_current_screen_state(self) -> None:
        current_screen = self.screen
        # Best-effort flush of in-progress widget state into app state.
        for hook_name in (
            "_capture_draft",
            "_persist_to_state",
            "_persist_for_navigation",
        ):
            hook = getattr(current_screen, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    # Exit flow should never fail because a screen-specific draft hook errored.
                    pass
