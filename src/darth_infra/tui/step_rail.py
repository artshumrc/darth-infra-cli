"""Top step rail widget for wizard navigation."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button

from .steps import STEP_LABELS, STEP_ORDER


class StepRail(Vertical):
    """Clickable top nav for wizard steps."""

    def __init__(self, current_step: str) -> None:
        super().__init__(classes="step-rail")
        self._current_step = current_step

    def compose(self) -> ComposeResult:
        midpoint = (len(STEP_ORDER) + 1) // 2
        rows = [STEP_ORDER[:midpoint], STEP_ORDER[midpoint:]]
        for row in rows:
            with Horizontal(classes="step-row"):
                for step in row:
                    variant = "primary" if step == self._current_step else "default"
                    yield Button(
                        STEP_LABELS[step],
                        id=f"step_nav_{step}",
                        variant=variant,
                        compact=True,
                        disabled=step == self._current_step,
                    )
