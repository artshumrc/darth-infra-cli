"""Save, quit, and conflict-resolution overlays for the Guided editor.

These modal screens complete the editor's session-safety workflows (ticket 15).
They are deliberately thin: each collects a decision and returns it to the shell,
which owns the document interaction. Keeping the document out of the dialogs
means the same three-way-merge and reversion semantics drive every path.

* :class:`QuitDecisionScreen` — the quit prompt. A valid dirty draft offers
  Save / Discard / Cancel; an invalid dirty draft offers Return to fix /
  Discard (never Save, so invalid state is never written and never silently
  dropped).
* :class:`MergePreviewScreen` — shows the exact patch a disjoint automatic
  merge would write to disk, and confirms before writing.
* :class:`ConflictResolverScreen` — presents each true conflict with its
  baseline, disk, and draft values and lets the operator choose per conflict, or
  cancel (leaving both draft and disk untouched).
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, Static

from ...config.document import ABSENT, MergeConflict

# Per-conflict choices returned by the resolver.
CHOICE_DRAFT = "draft"
CHOICE_DISK = "disk"


def format_value(value: Any) -> str:
    """Render a merge value for display, distinguishing an absent field."""
    if value is ABSENT:
        return "(not present)"
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(v) for v in value) + "]"
    return str(value)


class QuitDecisionScreen(ModalScreen[str]):
    """Prompt shown when quitting with unsaved draft changes.

    Returns one of ``"save"``, ``"discard"``, ``"cancel"``, or ``"return"``.
    ``offer_save`` is true only for a valid, saveable existing-project draft;
    ``valid`` gates whether an invalid draft is offered Return-to-fix instead of
    Save. An invalid draft is never offered Save, so quitting can never write or
    silently discard invalid configuration.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, *, valid: bool, offer_save: bool) -> None:
        super().__init__()
        self._valid = valid
        self._offer_save = offer_save

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-dialog"):
            yield Static("Unsaved changes", classes="section-title")
            if self._valid:
                yield Static(
                    "You have unsaved changes to the configuration draft."
                )
            else:
                yield Static(
                    "Your draft has validation errors, so it cannot be saved as "
                    "is. Return to fix them, or discard the draft."
                )
            with Horizontal(id="quit-buttons"):
                if self._offer_save:
                    yield Button("Save", id="quit-save", variant="primary")
                    yield Button("Discard", id="quit-discard", variant="error")
                    yield Button("Cancel", id="quit-cancel")
                elif self._valid:
                    yield Button("Discard", id="quit-discard", variant="error")
                    yield Button("Cancel", id="quit-cancel", variant="primary")
                else:
                    yield Button("Return to fix", id="quit-return", variant="primary")
                    yield Button("Discard", id="quit-discard", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        mapping = {
            "quit-save": "save",
            "quit-discard": "discard",
            "quit-cancel": "cancel",
            "quit-return": "return",
        }
        self.dismiss(mapping.get(event.button.id or "", "cancel"))

    def action_cancel(self) -> None:
        self.dismiss("cancel")


class MergePreviewScreen(ModalScreen[bool]):
    """Show the exact patch a disjoint automatic merge will write, then confirm.

    Returns ``True`` when the operator accepts the merged write. Cancelling
    leaves the draft (and the file on disk) unchanged.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, patch: str, filename: str) -> None:
        super().__init__()
        self._patch = patch
        self._filename = filename

    def compose(self) -> ComposeResult:
        with Vertical(id="merge-dialog"):
            yield Static("External changes merged", classes="section-title")
            yield Static(
                f"{self._filename} changed on disk. Your changes and the external "
                "changes did not conflict and were merged automatically. This is "
                "the exact patch that will be written:",
                id="merge-body",
            )
            with VerticalScroll(id="merge-patch"):
                yield Static(
                    self._patch or "(no textual change)",
                    id="merge-patch-body",
                    classes="review-toml",
                    markup=False,
                )
            with Horizontal(id="merge-buttons"):
                yield Button("Save merged", id="merge-confirm", variant="primary")
                yield Button("Cancel", id="merge-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "merge-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConflictResolverScreen(ModalScreen[dict[str, str] | None]):
    """Resolve true three-way-merge conflicts, one choice per field.

    Each conflict shows its baseline, disk (external), and draft (yours) values.
    The operator chooses which side wins each field. Returns a mapping of
    conflict path to :data:`CHOICE_DRAFT` / :data:`CHOICE_DISK`, or ``None`` when
    cancelled — in which case the shell leaves both the draft and the disk file
    untouched.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, conflicts: list[MergeConflict]) -> None:
        super().__init__()
        self._conflicts = conflicts
        # radioset id -> conflict path
        self._radio_paths: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="conflict-dialog"):
            yield Static("Resolve conflicts", classes="section-title")
            yield Static(
                f"{len(self._conflicts)} field(s) were changed both on disk and "
                "in your draft. Choose which value to keep for each. Cancelling "
                "leaves your draft and the file on disk unchanged.",
                id="conflict-body",
            )
            with VerticalScroll(id="conflict-list"):
                for index, conflict in enumerate(self._conflicts):
                    radio_id = f"conflict-choice-{index}"
                    self._radio_paths[radio_id] = conflict.path
                    yield Static(conflict.path, classes="conflict-path", markup=False)
                    yield Static(
                        f"was: {format_value(conflict.baseline)}",
                        classes="conflict-baseline",
                        markup=False,
                    )
                    yield RadioSet(
                        RadioButton(
                            f"Keep yours: {format_value(conflict.draft)}",
                            value=True,
                        ),
                        RadioButton(f"Use theirs: {format_value(conflict.disk)}"),
                        id=radio_id,
                    )
            with Horizontal(id="conflict-buttons"):
                yield Button(
                    "Resolve and save", id="conflict-resolve", variant="primary"
                )
                yield Button("Cancel", id="conflict-cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "conflict-cancel":
            self.dismiss(None)
            return
        if event.button.id == "conflict-resolve":
            self.dismiss(self._collect_choices())

    def _collect_choices(self) -> dict[str, str]:
        choices: dict[str, str] = {}
        for radio_id, path in self._radio_paths.items():
            radio = self.query_one(f"#{radio_id}", RadioSet)
            # Index 0 is "keep yours" (draft); index 1 is "use theirs" (disk).
            choices[path] = CHOICE_DISK if radio.pressed_index == 1 else CHOICE_DRAFT
        return choices

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "QuitDecisionScreen",
    "MergePreviewScreen",
    "ConflictResolverScreen",
    "CHOICE_DRAFT",
    "CHOICE_DISK",
    "format_value",
]
