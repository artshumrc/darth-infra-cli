"""Reusable master-detail interaction for repeatable configuration resources.

Repeatable resources — services now, and routing rules, buckets, and secrets in
later slices — share one interaction: a searchable list of records beside an
editor for the selected record, with Add, Duplicate, and Delete actions. This
module packages that interaction as :class:`MasterDetailSection` so every
collection editor behaves the same way.

The base owns only the *generic* mechanics: search filtering, the record list
with text-and-color state markers, selection, and the Add/Duplicate/Delete
workflow (including a confirmation dialog and blocked deletion for referenced
records). It never touches the TOML document or any resource-specific field; a
subclass supplies record metadata and builds the detail editor through the hook
methods below. This keeps the document AST and resource internals out of the
reusable interface.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

# Text-and-color state markers. Color alone never carries meaning: each marker
# is a distinct glyph so record state survives without color perception.
STATE_INVALID = "invalid"
STATE_MODIFIED = "modified"
STATE_OK = "ok"

_MARKERS = {
    STATE_INVALID: "✗",  # ✗ invalid
    STATE_MODIFIED: "●",  # ● unsaved changes
    STATE_OK: "·",  # · clean
}


class ConfirmScreen(ModalScreen[bool]):
    """A small yes/no confirmation dialog returning ``True`` when confirmed."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(
        self,
        title: str,
        body: str,
        *,
        confirm_label: str = "Confirm",
        confirm_variant: str = "error",
    ) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label
        self._confirm_variant = confirm_variant

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._title, id="confirm-title", classes="section-title")
            yield Static(self._body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button(
                    self._confirm_label,
                    id="confirm-yes",
                    variant=self._confirm_variant,
                )
                yield Button("Cancel", id="confirm-no", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MasterDetailSection(VerticalScroll):
    """Base widget for a searchable list of records beside a record editor.

    Subclasses set :attr:`section_title`, :attr:`item_noun`, and
    :attr:`empty_message`, and implement the record hooks. They must not need to
    override the composition or the Add/Duplicate/Delete/search mechanics.
    """

    section_title: str = ""
    item_noun: str = "item"
    empty_message: str = "Nothing configured yet."

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document
        self._selected: int | None = None
        self._search: str = ""
        self._visible: list[int] = []
        self._detail: Any = None

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self.section_title, classes="section-title")
        with Horizontal(id="md-toolbar"):
            yield Input(
                placeholder=f"Search {self.item_noun}s",
                id="md-search",
                classes="md-search",
            )
            yield Button("+ Add", id="md-add", variant="success", compact=True)
            yield Button("Duplicate", id="md-duplicate", compact=True)
            yield Button("Delete", id="md-delete", variant="error", compact=True)
        yield Static(
            f"{_MARKERS[STATE_INVALID]} invalid   "
            f"{_MARKERS[STATE_MODIFIED]} unsaved changes",
            id="md-legend",
            classes="field-help",
        )
        with Horizontal(id="md-body"):
            yield ListView(id="md-list", classes="md-list")
            yield Container(id="md-detail", classes="md-detail")
        yield Static("", id="md-status", classes="md-status")

    def on_mount(self) -> None:
        self._refresh_list()
        if self.item_count() > 0:
            self.run_worker(self._select(0, focus_detail=False), exclusive=False)
        else:
            self._update_status()

    # -- record hooks (subclass responsibility) ----------------------------

    def item_count(self) -> int:
        raise NotImplementedError

    def item_label(self, index: int) -> str:
        """Human-readable label for the record at ``index`` in the list."""
        raise NotImplementedError

    def item_state(self, index: int) -> str:
        """One of :data:`STATE_INVALID`, :data:`STATE_MODIFIED`, :data:`STATE_OK`."""
        raise NotImplementedError

    def build_detail(self, index: int) -> Any:
        """Return the detail editor widget for the record at ``index``."""
        raise NotImplementedError

    def create_record(self) -> int:
        """Create a new empty record and return its index."""
        raise NotImplementedError

    def duplicate_record(self, index: int) -> int:
        """Duplicate the record at ``index`` and return the new record's index."""
        raise NotImplementedError

    def blocking_references(self, index: int) -> list[str]:
        """Return human-readable references that must block deleting ``index``."""
        raise NotImplementedError

    def delete_record(self, index: int) -> None:
        """Remove the record at ``index`` from the document."""
        raise NotImplementedError

    def commit_detail(self) -> None:
        """Flush the current detail editor's edits into the draft."""
        if self._detail is not None and hasattr(self._detail, "commit_all"):
            self._detail.commit_all()

    def validate_detail(self) -> list:
        """Validate the current detail for save; return invalid fields to focus."""
        if self._detail is not None and hasattr(self._detail, "validate_for_save"):
            return list(self._detail.validate_for_save())
        return []

    def mark_modified(self, index: int) -> None:  # pragma: no cover - overridden
        """Note that the record at ``index`` has unsaved changes."""

    # -- list rendering ----------------------------------------------------

    def _matches_search(self, index: int) -> bool:
        if not self._search:
            return True
        return self._search.lower() in self.item_label(index).lower()

    def _refresh_list(self) -> None:
        list_view = self.query_one("#md-list", ListView)
        keep = self._selected
        list_view.clear()
        self._visible = []
        count = self.item_count()
        if count == 0:
            list_view.append(
                ListItem(Static(self.empty_message, classes="md-empty"))
            )
            self._update_status()
            return
        selected_row: int | None = None
        for index in range(count):
            if not self._matches_search(index):
                continue
            marker = _MARKERS[self.item_state(index)]
            row = ListItem(Static(f"{marker} {self.item_label(index)}"))
            if index == keep:
                selected_row = len(self._visible)
            self._visible.append(index)
            list_view.append(row)
        if selected_row is not None:
            list_view.index = selected_row
        self._update_status()

    def _update_status(self) -> None:
        status = self.query_one("#md-status", Static)
        count = self.item_count()
        if count == 0:
            status.update(self.empty_message)
            return
        noun = self.item_noun
        plural = noun if count == 1 else f"{noun}s"
        if self._selected is None:
            status.update(f"{count} {plural}. Select one to edit.")
        else:
            status.update(
                f"Editing {noun} {self._selected + 1} of {count}: "
                f"{self.item_label(self._selected)}"
            )

    # -- selection ---------------------------------------------------------

    async def _select(self, index: int, *, focus_detail: bool = True) -> None:
        # Persist the currently open record before switching away from it.
        if self._detail is not None:
            self.commit_detail()
        self._selected = index
        host = self.query_one("#md-detail", Container)
        await host.remove_children()
        self._detail = None
        if index is None or not (0 <= index < self.item_count()):
            self._update_status()
            return
        detail = self.build_detail(index)
        self._detail = detail
        await host.mount(detail)
        self._refresh_list()
        if focus_detail and hasattr(detail, "focus_first"):
            detail.focus_first()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "md-list":
            return
        event.stop()
        row = event.list_view.index
        if row is None or row >= len(self._visible):
            return
        target = self._visible[row]
        if target != self._selected:
            await self._select(target)

    # -- actions -----------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "md-add":
            event.stop()
            await self._handle_add()
        elif button_id == "md-duplicate":
            event.stop()
            await self._handle_duplicate()
        elif button_id == "md-delete":
            event.stop()
            await self._handle_delete()

    async def _handle_add(self) -> None:
        if self._detail is not None:
            self.commit_detail()
        index = self.create_record()
        self._search = ""
        self.query_one("#md-search", Input).value = ""
        self._refresh_list()
        await self._select(index)

    async def _handle_duplicate(self) -> None:
        if self._selected is None:
            self.app.notify(
                f"Select a {self.item_noun} to duplicate.", severity="warning"
            )
            return
        self.commit_detail()
        index = self.duplicate_record(self._selected)
        self._search = ""
        self.query_one("#md-search", Input).value = ""
        self._refresh_list()
        await self._select(index)
        self.app.notify(
            f"Duplicated {self.item_noun}. Give it a unique name before saving.",
            severity="information",
        )

    async def _handle_delete(self) -> None:
        if self._selected is None:
            self.app.notify(
                f"Select a {self.item_noun} to delete.", severity="warning"
            )
            return
        index = self._selected
        refs = self.blocking_references(index)
        if refs:
            joined = "; ".join(refs)
            self.app.notify(
                f"Cannot delete this {self.item_noun}: still referenced by "
                f"{joined}. Remove those references first.",
                severity="error",
                timeout=8,
            )
            return
        label = self.item_label(index)

        def _after_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._do_delete(index), exclusive=False)

        self.app.push_screen(
            ConfirmScreen(
                f"Delete {self.item_noun}",
                f"Delete {self.item_noun} '{label}'? This cannot be undone "
                "until you discard the draft.",
                confirm_label="Delete",
            ),
            _after_confirm,
        )

    async def _do_delete(self, index: int) -> None:
        self.delete_record(index)
        self._detail = None
        remaining = self.item_count()
        if remaining == 0:
            self._selected = None
            host = self.query_one("#md-detail", Container)
            await host.remove_children()
            self._refresh_list()
            self._update_status()
            return
        next_index = min(index, remaining - 1)
        self._selected = None
        self._refresh_list()
        await self._select(next_index, focus_detail=False)

    # -- search ------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "md-search":
            return
        event.stop()
        self._search = event.value.strip()
        self._refresh_list()

    # -- save hooks --------------------------------------------------------

    def validate_all(self) -> list:
        """Commit and validate the open record for a save attempt.

        Returns the invalid fields (first is the one to focus), matching the
        interface the shell uses for every editable section.
        """
        self.commit_detail()
        invalid = self.validate_detail()
        self._refresh_list()
        return invalid

    def after_save(self) -> None:
        """Refresh state after a successful save."""
        if self._detail is not None and hasattr(self._detail, "after_save"):
            self._detail.after_save()
        self._refresh_list()


__all__ = [
    "ConfirmScreen",
    "MasterDetailSection",
    "STATE_INVALID",
    "STATE_MODIFIED",
    "STATE_OK",
]
