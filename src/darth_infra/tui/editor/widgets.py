"""Reusable field widgets for the Guided editor.

Every editable setting is wrapped in an :class:`EditableField`. The wrapper is
the shared visual and interaction foundation the later section editors build on:
it renders a label, an explicit/default badge, schema-backed help (with the
effective default and constraints), an adjacent error line, and it tracks
*touched* state so validation only surfaces after a field has been visited.

Fields do not decide *whether* a value is valid — the owning section does that
through the document/model semantics — but a field owns *presenting* validity:
it exposes :meth:`EditableField.show_error` / :meth:`EditableField.clear_error`
and reports blur and change events so the section can validate on blur and clear
live once an error is showing.

Read-only, CLI-maintained metadata uses :class:`ReadOnlyField`, which renders no
focusable control and therefore cannot receive edit focus.
"""

from __future__ import annotations

import re
from typing import Any

from textual import events
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from .theme import (
    BADGE_DEFAULT,
    BADGE_EXPLICIT,
    BADGE_READ_ONLY,
    ERROR_SYMBOL,
)


def dom_slug(field_path: str) -> str:
    """Return a stable DOM-id-safe slug for a concrete field path.

    ``project.name`` -> ``project-name``; ``project.tags`` -> ``project-tags``.
    """
    return re.sub(r"[^0-9A-Za-z]+", "-", field_path).strip("-")


class EditableField(Vertical):
    """Base wrapper for one editable setting.

    Subclasses implement the concrete control by overriding
    :meth:`_compose_control`, :meth:`current_value`, and :meth:`commit`.
    """

    class Changed(Message):
        """Posted when the field's value changes (bubbles to the section)."""

        def __init__(self, field: "EditableField") -> None:
            self.field = field
            super().__init__()

    class Blurred(Message):
        """Posted when focus leaves the field (bubbles to the section)."""

        def __init__(self, field: "EditableField") -> None:
            self.field = field
            super().__init__()

    def __init__(
        self,
        *,
        field_path: str,
        document: Any,
        label: str,
        help: str,
        default_display: str = "",
        constraints: str = "",
        example: str | None = None,
        required: bool = False,
    ) -> None:
        self.slug = dom_slug(field_path)
        super().__init__(id=f"field-{self.slug}", classes="editable-field")
        self.field_path = field_path
        self.document = document
        self.label = label
        self.help = help
        self.default_display = default_display
        self.constraints = constraints
        self.example = example
        self.required = required
        self.touched = False
        self.error: str | None = None

    # -- composition -------------------------------------------------------

    def compose(self):
        with Horizontal(classes="field-label-row"):
            label = self.label + (" *" if self.required else "")
            yield Label(label, classes="field-label")
            yield Static(
                self._badge_text(), id=f"badge-{self.slug}", classes="field-badge"
            )
        yield from self._compose_control()
        yield Static(self._help_text(), id=f"help-{self.slug}", classes="field-help")
        yield Static("", id=f"error-{self.slug}", classes="field-error")

    def _compose_control(self):  # pragma: no cover - overridden
        raise NotImplementedError
        yield  # keep this a generator

    # -- values (subclass responsibility) ----------------------------------

    def current_value(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def commit(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- help / badges -----------------------------------------------------

    def _help_text(self) -> str:
        parts = [self.help]
        if self.default_display:
            parts.append(f"Default: {self.default_display}")
        if self.constraints:
            parts.append(self.constraints)
        return "   ·   ".join(p for p in parts if p)

    def expanded_help(self) -> str:
        """Longer help shown by F1: meaning, default, constraints, example."""
        lines = [self.help]
        if self.default_display:
            lines.append(f"Effective default: {self.default_display}")
        if self.constraints:
            lines.append(f"Constraints: {self.constraints}")
        if self.example:
            lines.append(f"Example: {self.example}")
        return "\n\n".join(lines)

    def _badge_text(self) -> str:
        try:
            explicit = self.document.is_explicit(self.field_path)
        except Exception:
            explicit = False
        return BADGE_EXPLICIT if explicit else BADGE_DEFAULT

    def refresh_badge(self) -> None:
        badge = self.query_one(f"#badge-{self.slug}", Static)
        text = self._badge_text()
        badge.update(text)
        badge.set_class(text == BADGE_EXPLICIT, "badge-explicit")
        badge.set_class(text == BADGE_DEFAULT, "badge-default")

    # -- error presentation ------------------------------------------------

    def show_error(self, message: str) -> None:
        self.error = message
        widget = self.query_one(f"#error-{self.slug}", Static)
        widget.update(f"{ERROR_SYMBOL} {message}")
        widget.display = True
        self.add_class("field-invalid")

    def clear_error(self) -> None:
        self.error = None
        widget = self.query_one(f"#error-{self.slug}", Static)
        widget.update("")
        widget.display = False
        self.remove_class("field-invalid")

    # -- event wiring ------------------------------------------------------

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self.touched = True
        self.post_message(self.Blurred(self))

    def _notify_changed(self) -> None:
        self.post_message(self.Changed(self))


class TextField(EditableField):
    """A single-line text control bound to a scalar string field."""

    def _compose_control(self):
        value = self.document.value(self.field_path)
        yield Input(
            value="" if value is None else str(value),
            id=f"input-{self.slug}",
            classes="field-input",
        )

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def current_value(self) -> str:
        return self._input().value.strip()

    def commit(self) -> None:
        text = self.current_value()
        if text == "":
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, text)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._notify_changed()


class StringListField(EditableField):
    """A comma-separated list of strings bound to an array field."""

    def _compose_control(self):
        value = self.document.value(self.field_path)
        text = ", ".join(str(item) for item in value) if value else ""
        yield Input(
            value=text,
            id=f"input-{self.slug}",
            classes="field-input",
        )

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def current_value(self) -> list[str]:
        raw = self._input().value
        return [part.strip() for part in raw.split(",") if part.strip()]

    def commit(self) -> None:
        # Always persist the parsed list (including an empty list) so model
        # validation can flag a missing required entry rather than silently
        # falling back to the omitted default.
        self.document.set(self.field_path, self.current_value())

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._notify_changed()


class KeyValueMapField(EditableField):
    """A key/value map editor bound to a ``*``-wildcard map field.

    Rows are committed to the document immediately (per key) so unrelated map
    entries and their formatting survive. ``field_path`` is the map container
    (e.g. ``project.tags``); individual keys are addressed as
    ``project.tags.<key>``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._editing_key: str | None = None
        self._keys: list[str] = []

    def _compose_control(self):
        yield ListView(id=f"list-{self.slug}", classes="kv-list")
        with Horizontal(classes="kv-entry-row"):
            yield Input(placeholder="key", id=f"kvkey-{self.slug}", classes="kv-key")
            yield Input(
                placeholder="value", id=f"kvval-{self.slug}", classes="kv-value"
            )
        with Horizontal(classes="kv-button-row"):
            yield Button(
                "+ Add", id=f"kvadd-{self.slug}", variant="success", compact=True
            )
            yield Button(
                "Remove", id=f"kvremove-{self.slug}", variant="error", compact=True
            )

    def on_mount(self) -> None:
        self._refresh_rows()

    def _current_map(self) -> dict[str, str]:
        value = self.document.value(self.field_path)
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items()}

    def current_value(self) -> dict[str, str]:
        return self._current_map()

    def commit(self) -> None:
        # Map rows are committed live per action; nothing to flush here.
        return

    def configured_count(self) -> int:
        return len(self._current_map())

    def _refresh_rows(self) -> None:
        mapping = self._current_map()
        self._keys = sorted(mapping)
        list_view = self.query_one(f"#list-{self.slug}", ListView)
        list_view.clear()
        if not self._keys:
            list_view.append(ListItem(Static("(none configured)", classes="kv-empty")))
            return
        for key in self._keys:
            list_view.append(ListItem(Static(f"{key} = {mapping[key]}")))

    def _key_input(self) -> Input:
        return self.query_one(f"#kvkey-{self.slug}", Input)

    def _value_input(self) -> Input:
        return self.query_one(f"#kvval-{self.slug}", Input)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        index = event.list_view.index
        if index is None or index >= len(self._keys):
            return
        key = self._keys[index]
        self._editing_key = key
        self._key_input().value = key
        self._value_input().value = self._current_map().get(key, "")

    def on_input_changed(self, event: Input.Changed) -> None:
        # The key/value inputs are internal to this control; do not let their
        # changes read as a scalar edit of the map field.
        event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == f"kvadd-{self.slug}":
            self._add_row()
        elif button_id == f"kvremove-{self.slug}":
            self._remove_row()

    def _add_row(self) -> None:
        key = self._key_input().value.strip()
        value = self._value_input().value.strip()
        if not key:
            self.app.notify("A key is required to add a map entry", severity="error")
            return
        # Renaming an existing selection removes the old key first.
        if self._editing_key is not None and self._editing_key != key:
            self.document.reset(f"{self.field_path}.{self._editing_key}")
        self.document.set(f"{self.field_path}.{key}", value)
        self._clear_entry()
        self._refresh_rows()
        self._notify_changed()

    def _remove_row(self) -> None:
        key = self._editing_key or self._key_input().value.strip()
        if not key:
            return
        self.document.reset(f"{self.field_path}.{key}")
        self._clear_entry()
        self._refresh_rows()
        self._notify_changed()

    def _clear_entry(self) -> None:
        self._editing_key = None
        self._key_input().value = ""
        self._value_input().value = ""


class ReadOnlyField(Vertical):
    """Display-only CLI-maintained metadata.

    It renders a value and a READ-ONLY badge but no focusable control, so it can
    be inspected but never receives edit focus.
    """

    def __init__(
        self,
        *,
        field_path: str,
        document: Any,
        label: str,
        help: str,
    ) -> None:
        self.slug = dom_slug(field_path)
        super().__init__(id=f"field-{self.slug}", classes="editable-field readonly-field")
        self.field_path = field_path
        self.document = document
        self.label = label
        self.help = help

    def compose(self):
        with Horizontal(classes="field-label-row"):
            yield Label(self.label, classes="field-label")
            yield Static(
                BADGE_READ_ONLY, id=f"badge-{self.slug}", classes="field-badge badge-readonly"
            )
        value = self.document.value(self.field_path)
        yield Static(
            "(not set)" if value in (None, "") else str(value),
            id=f"value-{self.slug}",
            classes="readonly-value",
        )
        yield Static(self.help, id=f"help-{self.slug}", classes="field-help")


__all__ = [
    "dom_slug",
    "EditableField",
    "TextField",
    "StringListField",
    "KeyValueMapField",
    "ReadOnlyField",
]
