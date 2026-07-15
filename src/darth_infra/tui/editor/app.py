"""The Guided configuration editor application shell.

This is the non-linear, document-preserving editor introduced by the
``tui-configuration-editor`` epic. It is driven entirely by a
:class:`~darth_infra.config.document.ProjectDocument` — it never constructs
configuration through the legacy wizard bridge — and presents the nine canonical
navigation destinations. Ticket 04 implements the Project destination; the rest
are reachable placeholders.

The shell is kept internal (not wired to any CLI command) until the atomic
cutover in ticket 16; ``darth-infra tui`` continues to launch the legacy wizard.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Static

from ..field_registry import Section
from ...config.document import (
    DocumentConflictError,
    DocumentValidationError,
    ProjectDocument,
)
from .navigation import (
    IMPLEMENTED_SECTIONS,
    SECTION_LABELS,
    SECTION_ORDER,
    nav_button_id,
)
from .aws_discovery import AwsDiscovery, OfflineAwsDiscovery
from .database import DatabaseSection
from .network import NetworkSection
from .sections import PlaceholderSection, ProjectSection
from .services import ServicesSection
from .theme import CONTROL_ROOM_THEME, THEME_NAME
from .widgets import EditableField

# Minimum usable terminal size. Below this the editor refuses to render a broken
# form and shows a minimum-size message instead.
MIN_WIDTH = 80
MIN_HEIGHT = 24


class FieldHelpScreen(ModalScreen[None]):
    """Expanded, F1-triggered help for the focused field."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=True)]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="field-help-dialog"):
            yield Static(self._title, id="field-help-title", classes="section-title")
            yield Static(self._body, id="field-help-body")
            yield Button("Close", id="field-help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "field-help-close":
            self.dismiss(None)

    def action_dismiss(self, result: Any = None) -> None:
        self.dismiss(None)


class ConfigEditorApp(App[None]):
    """Non-linear, document-preserving Guided editor for a project document."""

    CSS = """
    Screen {
        background: $background;
    }
    #too-small {
        display: none;
        align: center middle;
        width: 100%;
        height: 100%;
        color: $warning;
        text-align: center;
    }
    #editor-main {
        width: 100%;
        height: 1fr;
    }
    #nav-rail {
        width: 22;
        height: 100%;
        border-right: solid $panel;
        padding: 1 1;
        background: $surface;
    }
    #nav-rail .nav-heading {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #nav-rail Button {
        width: 100%;
        margin-bottom: 0;
        border: none;
        height: 1;
    }
    .nav-active {
        color: $accent;
        text-style: bold;
    }
    .nav-unavailable {
        color: $text-muted;
    }
    #content-host {
        width: 1fr;
        height: 100%;
        padding: 1 2;
    }
    .section-content {
        width: 100%;
        height: 100%;
    }
    .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .editable-field {
        height: auto;
        margin-bottom: 1;
        border-left: solid $panel;
        padding: 0 1;
    }
    .editable-field.field-invalid {
        border-left: solid $error;
    }
    .field-label-row {
        height: auto;
        width: 100%;
    }
    .field-label {
        text-style: bold;
        width: 1fr;
    }
    .field-badge {
        width: auto;
        color: $text-muted;
    }
    .badge-explicit {
        color: $accent;
    }
    .badge-default, .badge-readonly {
        color: $text-muted;
    }
    .badge-automatic {
        color: $accent;
    }
    .aws-control {
        height: auto;
    }
    .mode-row, .aws-actions {
        height: auto;
    }
    .aws-select {
        width: 100%;
    }
    .aws-multiselect {
        height: auto;
        max-height: 6;
        border: round $panel;
    }
    .aws-status {
        height: auto;
        color: $text-muted;
    }
    .aws-status.status-loading {
        color: $accent;
    }
    .aws-status.status-results {
        color: $success;
    }
    .aws-status.status-empty {
        color: $warning;
    }
    .aws-status.status-failure {
        color: $error;
    }
    .verify-status {
        width: auto;
    }
    .verify-status.verify-verified {
        color: $success;
    }
    .verify-status.verify-failed {
        color: $error;
    }
    .verify-status.verify-none {
        color: $text-muted;
    }
    .field-input {
        margin: 0;
    }
    .field-help {
        color: $text-muted;
        height: auto;
    }
    .field-error {
        display: none;
        color: $error;
        height: auto;
    }
    .readonly-value {
        color: $text;
    }
    .kv-list {
        height: auto;
        max-height: 6;
        border: round $panel;
    }
    .kv-entry-row, .kv-button-row {
        height: auto;
    }
    .kv-key, .kv-value {
        width: 1fr;
    }
    #save-continue {
        margin-top: 1;
    }
    #field-help-dialog {
        width: 70;
        max-width: 90%;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #md-toolbar {
        height: auto;
        width: 100%;
    }
    .md-search {
        width: 1fr;
        margin: 0 1 0 0;
    }
    #md-toolbar Button {
        margin: 0 0 0 1;
    }
    #md-legend {
        height: auto;
        margin-bottom: 1;
    }
    #md-body {
        height: 1fr;
        width: 100%;
    }
    .md-list {
        width: 32;
        min-width: 20;
        height: 100%;
        border-right: solid $panel;
    }
    .md-detail {
        width: 1fr;
        height: 100%;
        padding: 0 1;
        overflow-y: auto;
    }
    .md-status {
        height: auto;
        color: $text-muted;
    }
    .md-empty {
        color: $text-muted;
    }
    #confirm-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-buttons {
        height: auto;
        margin-top: 1;
    }
    #confirm-buttons Button {
        margin: 0 1 0 0;
    }
    #impact-dialog {
        width: 70;
        max-width: 90%;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #impact-list {
        height: auto;
        max-height: 10;
        margin: 1 0;
        overflow-y: auto;
    }
    .impact-item {
        height: auto;
        color: $warning;
    }
    #impact-buttons {
        height: auto;
        margin-top: 1;
    }
    #impact-buttons Button {
        margin: 0 1 0 0;
    }
    .detail-form {
        height: auto;
    }
    .field-textarea {
        height: 6;
        border: round $panel;
    }
    .nested-collection {
        height: auto;
        border: round $panel;
        padding: 0 1;
        margin-bottom: 1;
    }
    .nested-title {
        text-style: bold;
        color: $accent;
    }
    .nested-toolbar {
        height: auto;
    }
    .nested-toolbar Button {
        margin: 0 1 0 0;
    }
    .nested-body {
        height: auto;
    }
    .nested-list {
        width: 28;
        min-width: 16;
        height: auto;
        max-height: 8;
        border-right: solid $panel;
    }
    .nested-detail {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    .nested-form {
        height: auto;
    }
    .nested-status {
        height: auto;
        color: $text-muted;
    }
    """

    # Required bindings only. Bare n / p / q are deliberately absent: printable
    # keys must remain ordinary text input.
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
        Binding("ctrl+k", "command_palette", "Commands", show=True, priority=True),
        Binding("f1", "field_help", "Help", show=True, priority=True),
        Binding("escape", "close_overlay", "Back", show=True),
    ]

    def __init__(
        self,
        *,
        document: ProjectDocument,
        mode: str = "existing",
        discovery: AwsDiscovery | None = None,
    ) -> None:
        super().__init__()
        self._document = document
        self._mode = mode
        # AWS discovery/verification is injected. It defaults to an offline
        # adapter so the editor is fully usable — and saveable — without any AWS
        # credentials; production and tests supply a real or fake adapter.
        self._discovery: AwsDiscovery = discovery or OfflineAwsDiscovery()
        self.current_section: Section = Section.PROJECT
        self._section_widget: Any = None

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(
            f"Terminal too small.\nResize to at least {MIN_WIDTH}x{MIN_HEIGHT} "
            "to use the configuration editor.",
            id="too-small",
        )
        with Horizontal(id="editor-main"):
            with Vertical(id="nav-rail"):
                yield Static("Sections", classes="nav-heading")
                for section in SECTION_ORDER:
                    label = SECTION_LABELS[section]
                    available = section in IMPLEMENTED_SECTIONS
                    classes = "nav-item" if available else "nav-item nav-unavailable"
                    text = label if available else f"{label} (soon)"
                    yield Button(
                        text,
                        id=nav_button_id(section),
                        classes=classes,
                        compact=True,
                    )
            yield Container(id="content-host")
        yield Footer()

    async def on_mount(self) -> None:
        self.register_theme(CONTROL_ROOM_THEME)
        self.theme = THEME_NAME
        await self._show_section(Section.PROJECT)
        self._apply_min_size(self.size.width, self.size.height)

    # -- navigation --------------------------------------------------------

    async def _show_section(self, section: Section) -> None:
        self.current_section = section
        host = self.query_one("#content-host", Container)
        await host.remove_children()
        if section is Section.PROJECT:
            widget: Any = ProjectSection(self._document)
        elif section is Section.NETWORK:
            widget = NetworkSection(self._document, self._discovery)
        elif section is Section.SERVICES:
            widget = ServicesSection(self._document)
        elif section is Section.DATABASE:
            widget = DatabaseSection(self._document)
        else:
            widget = PlaceholderSection(section)
        self._section_widget = widget
        await host.mount(widget)
        self._refresh_nav_highlight()

    def _refresh_nav_highlight(self) -> None:
        for section in SECTION_ORDER:
            button = self.query_one(f"#{nav_button_id(section)}", Button)
            button.set_class(section == self.current_section, "nav-active")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        for section in SECTION_ORDER:
            if button_id == nav_button_id(section):
                event.stop()
                await self._show_section(section)
                return

    def on_project_section_save_continue_requested(
        self, event: ProjectSection.SaveContinueRequested
    ) -> None:
        event.stop()
        if self._handle_save():
            self._suggest_next_section()

    def on_network_section_save_continue_requested(
        self, event: NetworkSection.SaveContinueRequested
    ) -> None:
        event.stop()
        if self._handle_save():
            self._suggest_next_section()

    def on_database_section_save_continue_requested(
        self, event: DatabaseSection.SaveContinueRequested
    ) -> None:
        event.stop()
        if self._handle_save():
            self._suggest_next_section()

    # -- responsive --------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        self._apply_min_size(event.size.width, event.size.height)

    def _apply_min_size(self, width: int, height: int) -> None:
        too_small = width < MIN_WIDTH or height < MIN_HEIGHT
        self.query_one("#too-small", Static).display = too_small
        self.query_one("#editor-main", Horizontal).display = not too_small

    # -- actions -----------------------------------------------------------

    def action_save(self) -> None:
        self._handle_save()

    def _handle_save(self) -> bool:
        """Validate the current section and save; return True on a written save."""
        section = self._section_widget
        if not hasattr(section, "validate_all"):
            self.notify(
                "This section is not editable yet.", severity="warning"
            )
            return False

        invalid = section.validate_all()
        if invalid:
            first = invalid[0]
            inputs = first.query(Input)
            if inputs:
                inputs.first().focus()
            self.notify(
                f"Fix {len(invalid)} field error(s) before saving.",
                severity="error",
            )
            return False

        try:
            self._document.save()
        except DocumentConflictError:
            self.notify(
                "darth-infra.toml changed on disk; not saved. "
                "Reload to merge (arrives in a later slice).",
                severity="error",
            )
            return False
        except DocumentValidationError as exc:
            self.notify(f"Cannot save: {exc.error}", severity="error")
            return False

        if hasattr(section, "after_save"):
            section.after_save()
        self.notify(
            f"Saved {self._document.path.name}.", severity="information"
        )
        return True

    def _suggest_next_section(self) -> None:
        index = SECTION_ORDER.index(self.current_section)
        if index + 1 < len(SECTION_ORDER):
            nxt = SECTION_ORDER[index + 1]
            self.run_worker(self._show_section(nxt))
            self.notify(
                f"Suggested next: {SECTION_LABELS[nxt]}. "
                "Any section remains directly reachable.",
                severity="information",
            )

    def action_field_help(self) -> None:
        field = self._owning_field(self.focused)
        if field is None:
            self.notify("Focus a field to see its help.", severity="warning")
            return
        self.push_screen(FieldHelpScreen(field.label, field.expanded_help()))

    def action_close_overlay(self) -> None:
        # Close a modal/overlay if one is open; never exit the base editor.
        if len(self.screen_stack) > 1:
            self.pop_screen()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _owning_field(widget: Any) -> EditableField | None:
        node = widget
        while node is not None:
            if isinstance(node, EditableField):
                return node
            node = node.parent
        return None


__all__ = ["ConfigEditorApp"]
