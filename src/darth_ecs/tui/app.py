"""Textual TUI application for ``darth-ecs init``."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding

from ..config.models import ProjectConfig
from .screens.welcome import WelcomeScreen
from .screens.services import ServicesScreen
from .screens.rds import RdsScreen
from .screens.s3 import S3Screen
from .screens.alb import AlbScreen
from .screens.secrets import SecretsScreen
from .screens.review import ReviewScreen


class DarthEcsInitApp(App[None]):
    """Interactive setup wizard for darth-ecs projects."""

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
    .form-container {
        width: 80;
        max-height: 100%;
        height: auto;
        border: round $accent;
        padding: 1 2;
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
    Input {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.result_config: ProjectConfig | None = None
        # Shared state built up across screens
        self._state: dict = {
            "project_name": "",
            "vpc_name": "artshumrc-prod-standard",
            "aws_region": "us-east-1",
            "environments": ["prod"],
            "services": [],
            "rds": None,
            "s3_buckets": [],
            "alb_mode": "shared",
            "shared_alb_name": "",
            "certificate_arn": None,
            "secrets": [],
        }

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self._state))

    def advance_to(self, screen_name: str) -> None:
        """Navigate to the next screen in the wizard."""
        screens = {
            "services": ServicesScreen,
            "rds": RdsScreen,
            "s3": S3Screen,
            "alb": AlbScreen,
            "secrets": SecretsScreen,
            "review": ReviewScreen,
        }
        if screen_name in screens:
            self.push_screen(screens[screen_name](self._state))

    def finish(self, config: ProjectConfig) -> None:
        """Complete the wizard with a final config."""
        self.result_config = config
        self.exit()
