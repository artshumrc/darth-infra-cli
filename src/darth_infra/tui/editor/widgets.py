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

import asyncio
import re
from typing import Any, Callable

from textual import events
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    SelectionList,
    Static,
    TextArea,
)

from .aws_discovery import (
    AwsDiscovery,
    DiscoveryKind,
    DiscoveryRequest,
    DiscoveryResult,
    ResourceRecord,
    VerificationStatus,
)
from .collection import ConfirmScreen
from .theme import (
    BADGE_AUTOMATIC,
    BADGE_DEFAULT,
    BADGE_EXPLICIT,
    BADGE_READ_ONLY,
    ERROR_SYMBOL,
    VERIFY_FAILED,
    VERIFY_NOT_CHECKED,
    VERIFY_VERIFIED,
)


# Textual renamed the Select "no selection" sentinel from ``BLANK`` to ``NULL``
# in the 8.x line (and ``Select.BLANK`` now resolves to the boolean ``False``,
# which the widget rejects as an illegal value). Resolve the sentinel that the
# installed Textual actually understands so the editor works across our
# supported range (``textual>=1.0``).
SELECT_BLANK = Select.NULL if hasattr(Select, "NULL") else Select.BLANK


def dom_slug(field_path: str) -> str:
    """Return a stable DOM-id-safe slug for a concrete field path.

    ``project.name`` -> ``project-name``; ``project.tags`` -> ``project-tags``.
    """
    return re.sub(r"[^0-9A-Za-z]+", "-", field_path).strip("-")


# Sentinel distinguishing "no fallback supplied" from a real fallback of ``None``.
_NO_FALLBACK = object()


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
        fallback: Any = _NO_FALLBACK,
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
        # Effective default used to render this control when the draft cannot be
        # modeled (a sibling record is mid-edit) and the key is absent, so a
        # collection editor opened on a temporarily invalid draft still shows the
        # same default the model would apply once the draft parses again.
        self._fallback = fallback
        self.touched = False
        self.error: str | None = None
        # Sentinel until on_mount captures the loaded value; keeps every field
        # reporting "dirty" before it has a comparable baseline.
        self._loaded_key: Any = object()

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

    def on_mount(self) -> None:
        # Capture the loaded value so presence-preserving commits can tell an
        # untouched field (leave the document exactly as loaded) apart from an
        # edited one (write the new value).
        self._loaded_key = self._current_key()

    # -- values (subclass responsibility) ----------------------------------

    def current_value(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def commit(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _loaded_value(self) -> Any:
        """The field's initial value, robust to an invalid draft elsewhere.

        Prefers the model-computed effective value; when the draft cannot be
        modeled (for example a sibling repeated record is still half-entered)
        it falls back to the raw persisted value so the control can still render.
        """
        try:
            return self.document.value(self.field_path)
        except Exception:
            pass
        try:
            raw = self.document.raw_value(self.field_path)
        except Exception:
            raw = None
        if raw is None and self._fallback is not _NO_FALLBACK:
            return self._fallback
        return raw

    def _current_key(self) -> Any:
        """A comparable snapshot of the control's current value.

        Used to decide whether the field is dirty. Overridden by controls with a
        concrete value; the default has nothing to compare.
        """
        return None

    def is_dirty(self) -> bool:
        """Whether the control's value differs from the value it loaded with."""
        return self._current_key() != self._loaded_key

    def mark_committed(self) -> None:
        """Adopt the current value as the new loaded baseline after a save."""
        self._loaded_key = self._current_key()

    def validation_error(self) -> str | None:
        """A local, format-level error message, or ``None`` when well-formed.

        This covers only the control's own parsing (for example "not a whole
        number"); cross-field and model semantics remain the owning section's
        responsibility.
        """
        return None

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
        value = self._loaded_value()
        yield Input(
            value="" if value is None else str(value),
            id=f"input-{self.slug}",
            classes="field-input",
        )

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def current_value(self) -> str:
        return self._input().value.strip()

    def _current_key(self) -> Any:
        return self.current_value()

    def commit(self) -> None:
        if not self.is_dirty():
            return
        text = self.current_value()
        if text == "":
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, text)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._notify_changed()


class IntegerField(EditableField):
    """A single-line control bound to an integer (or nullable integer) field."""

    def _compose_control(self):
        value = self._loaded_value()
        yield Input(
            value="" if value is None else str(value),
            id=f"input-{self.slug}",
            classes="field-input",
        )

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def _raw(self) -> str:
        return self._input().value.strip()

    def current_value(self) -> int | None:
        raw = self._raw()
        if raw == "":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _current_key(self) -> Any:
        return self._raw()

    def validation_error(self) -> str | None:
        raw = self._raw()
        if raw == "":
            return None
        try:
            int(raw)
        except ValueError:
            return f"{self.label} must be a whole number"
        return None

    def commit(self) -> None:
        if not self.is_dirty():
            return
        raw = self._raw()
        if raw == "":
            self.document.reset(self.field_path)
            return
        try:
            self.document.set(self.field_path, int(raw))
        except ValueError:
            # Malformed input is surfaced by validation_error; do not corrupt
            # the draft with a non-integer value.
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._notify_changed()


class TextAreaField(EditableField):
    """A multi-line text control bound to a nullable string field.

    Used for inline scripts such as EC2 user-data content, where newlines are
    meaningful. An empty control removes the key (restoring omission); otherwise
    the full multi-line text is persisted verbatim.
    """

    def _compose_control(self):
        value = self.document.value(self.field_path)
        yield TextArea(
            "" if value is None else str(value),
            id=f"input-{self.slug}",
            classes="field-textarea",
        )

    def _textarea(self) -> TextArea:
        return self.query_one(f"#input-{self.slug}", TextArea)

    def current_value(self) -> str:
        return self._textarea().text

    def _current_key(self) -> Any:
        return self.current_value()

    def commit(self) -> None:
        if not self.is_dirty():
            return
        text = self.current_value()
        if text == "":
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        self._notify_changed()


class BooleanField(EditableField):
    """A checkbox bound to a boolean field."""

    def _compose_control(self):
        value = bool(self._loaded_value())
        yield Checkbox(
            self.label,
            value=value,
            id=f"input-{self.slug}",
            classes="field-checkbox",
        )

    def _checkbox(self) -> Checkbox:
        return self.query_one(f"#input-{self.slug}", Checkbox)

    def current_value(self) -> bool:
        return bool(self._checkbox().value)

    def _current_key(self) -> Any:
        return self.current_value()

    def commit(self) -> None:
        if not self.is_dirty():
            return
        self.document.set(self.field_path, self.current_value())

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self._notify_changed()


class SelectField(EditableField):
    """A dropdown bound to a scalar field with a fixed set of options."""

    def __init__(self, *, options: list[tuple[str, str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._options = options

    def _compose_control(self):
        value = self._loaded_value()
        current = None if value is None else str(value)
        yield Select(
            self._options,
            value=current if current is not None else SELECT_BLANK,
            allow_blank=True,
            id=f"input-{self.slug}",
            classes="field-select",
        )

    def _select(self) -> Select:
        return self.query_one(f"#input-{self.slug}", Select)

    def current_value(self) -> str | None:
        value = self._select().value
        if value is SELECT_BLANK:
            return None
        return str(value)

    def _current_key(self) -> Any:
        return self.current_value()

    def commit(self) -> None:
        if not self.is_dirty():
            return
        value = self.current_value()
        if value is None:
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, value)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._notify_changed()


class StringListField(EditableField):
    """A comma-separated list of strings bound to an array field."""

    def _compose_control(self):
        value = self._loaded_value()
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

    def _current_key(self) -> Any:
        return tuple(self.current_value())

    def commit(self) -> None:
        if not self.is_dirty():
            return
        # Persist the parsed list (including an empty list) so model validation
        # can flag a missing required entry rather than silently falling back to
        # the omitted default.
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

    When ``key_options`` is supplied, the key is chosen from a fixed set of
    values through a dropdown rather than typed freely. This is used for maps
    whose keys must reference an existing resource (for example a per-environment
    EC2 instance override keyed by service name), so the map cannot name a
    resource that does not exist.
    """

    def __init__(
        self,
        *,
        key_options: list[str] | None = None,
        key_placeholder: str = "key",
        value_placeholder: str = "value",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._editing_key: str | None = None
        self._keys: list[str] = []
        self._key_options = list(key_options) if key_options is not None else None
        self._key_placeholder = key_placeholder
        self._value_placeholder = value_placeholder

    def _compose_control(self):
        yield ListView(id=f"list-{self.slug}", classes="kv-list")
        with Horizontal(classes="kv-entry-row"):
            if self._key_options is not None:
                yield Select(
                    [(name, name) for name in self._key_options],
                    prompt=self._key_placeholder,
                    allow_blank=True,
                    id=f"kvkey-{self.slug}",
                    classes="kv-key",
                )
            else:
                yield Input(
                    placeholder=self._key_placeholder,
                    id=f"kvkey-{self.slug}",
                    classes="kv-key",
                )
            yield Input(
                placeholder=self._value_placeholder,
                id=f"kvval-{self.slug}",
                classes="kv-value",
            )
        with Horizontal(classes="kv-button-row"):
            yield Button(
                "+ Add", id=f"kvadd-{self.slug}", variant="success", compact=True
            )
            yield Button(
                "Remove", id=f"kvremove-{self.slug}", variant="error", compact=True
            )

    def on_mount(self) -> None:
        super().on_mount()
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

    def _value_input(self) -> Input:
        return self.query_one(f"#kvval-{self.slug}", Input)

    def _get_key(self) -> str:
        """Current key text, whether the key control is a Select or an Input."""
        if self._key_options is not None:
            select = self.query_one(f"#kvkey-{self.slug}", Select)
            value = select.value
            return "" if value is SELECT_BLANK else str(value)
        return self.query_one(f"#kvkey-{self.slug}", Input).value.strip()

    def _set_key(self, key: str) -> None:
        if self._key_options is not None:
            select = self.query_one(f"#kvkey-{self.slug}", Select)
            select.value = key if key in self._key_options else SELECT_BLANK
        else:
            self.query_one(f"#kvkey-{self.slug}", Input).value = key

    def _clear_key(self) -> None:
        if self._key_options is not None:
            self.query_one(f"#kvkey-{self.slug}", Select).value = SELECT_BLANK
        else:
            self.query_one(f"#kvkey-{self.slug}", Input).value = ""

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        index = event.list_view.index
        if index is None or index >= len(self._keys):
            return
        key = self._keys[index]
        self._editing_key = key
        self._set_key(key)
        self._value_input().value = self._current_map().get(key, "")

    def on_input_changed(self, event: Input.Changed) -> None:
        # The key/value inputs are internal to this control; do not let their
        # changes read as a scalar edit of the map field.
        event.stop()

    def on_select_changed(self, event: Select.Changed) -> None:
        # The key selector is internal to this control; do not let its changes
        # read as a scalar edit of the map field.
        if event.select.id == f"kvkey-{self.slug}":
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == f"kvadd-{self.slug}":
            self._add_row()
        elif button_id == f"kvremove-{self.slug}":
            self._remove_row()

    def _add_row(self) -> None:
        key = self._get_key()
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
        key = self._editing_key or self._get_key()
        if not key:
            return
        self.document.reset(f"{self.field_path}.{key}")
        self._clear_entry()
        self._refresh_rows()
        self._notify_changed()

    def _clear_entry(self) -> None:
        self._editing_key = None
        self._clear_key()
        self._value_input().value = ""


class MultiSelectField(EditableField):
    """A checklist multi-selector bound to an array-of-strings field.

    The set of choices is supplied by the owning section (for example the current
    service names for a database's ``expose_to`` list) rather than the schema,
    because the valid values are other configured resources. Selecting entries
    persists the chosen list in the order the options were given; selecting none
    removes the key, restoring omission. An empty option set renders an empty
    message so a blank control is never mistaken for a broken one.
    """

    def __init__(
        self,
        *,
        options: list[str],
        empty_message: str = "No options available.",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._options = list(options)
        self._empty_message = empty_message

    def _compose_control(self):
        value = self.document.value(self.field_path)
        current = {str(item) for item in value} if value else set()
        yield Static(
            self._empty_message,
            id=f"empty-{self.slug}",
            classes="field-help",
        )
        yield SelectionList[str](
            *[(opt, opt, opt in current) for opt in self._options],
            id=f"input-{self.slug}",
            classes="aws-multiselect",
        )

    def on_mount(self) -> None:
        super().on_mount()
        has_options = bool(self._options)
        self.query_one(f"#empty-{self.slug}", Static).display = not has_options
        self.query_one(f"#input-{self.slug}", SelectionList).display = has_options

    def _selection(self) -> SelectionList:
        return self.query_one(f"#input-{self.slug}", SelectionList)

    def current_value(self) -> list[str]:
        selected = {str(v) for v in self._selection().selected}
        # Preserve the stable option order rather than selection order.
        return [opt for opt in self._options if opt in selected]

    def _current_key(self) -> Any:
        return tuple(self.current_value())

    def commit(self) -> None:
        if not self.is_dirty():
            return
        values = self.current_value()
        if values:
            self.document.set(self.field_path, values)
        else:
            self.document.reset(self.field_path)

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if event.selection_list.id != f"input-{self.slug}":
            return
        event.stop()
        self.touched = True
        self._notify_changed()


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


class AwsBackedField(EditableField):
    """Shared behaviour for fields backed by optional AWS discovery.

    Adds three orthogonal capabilities on top of :class:`EditableField`, each
    independently switchable per field:

    * **Automatic/Override** (``optional``): an omittable, deploy-derived value
      shows an ``AUTO`` badge and hides its control until the user opts into an
      explicit Override. Returning an existing value to Automatic asks for
      confirmation and removes the persisted key.
    * **Discovery** (``discovery_kind``): a "Select from AWS" action lists
      candidate resources through the injected adapter, distinguishing loading,
      results, empty, and failure — and never silently replacing the value.
    * **Verification** (``verifiable``): a user-triggered check that reports
      ``Not checked`` / ``Verified`` / ``Check failed`` and never blocks a save.

    Concrete value handling (scalar versus list) is left to subclasses.
    """

    class RecordSelected(Message):
        """Posted when the user picks a discovered record.

        Lets the owning section capture parent context (a chosen VPC's id, a
        chosen ALB's ARN) so dependent discovery stays scoped.
        """

        def __init__(self, field: "AwsBackedField", record: ResourceRecord) -> None:
            self.field = field
            self.record = record
            super().__init__()

    def __init__(
        self,
        *,
        discovery: AwsDiscovery | None = None,
        discovery_kind: DiscoveryKind | None = None,
        verifiable: bool = False,
        optional: bool = False,
        context_provider: Callable[[DiscoveryKind | None], dict[str, Any]]
        | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._discovery = discovery
        self._discovery_kind = discovery_kind
        self._verifiable = verifiable
        self.optional = optional
        self._context_provider = context_provider
        self._automatic = optional and not self._is_explicit_safe()
        self._records_by_value: dict[str, ResourceRecord] = {}

    # -- helpers -----------------------------------------------------------

    def _is_explicit_safe(self) -> bool:
        try:
            return bool(self.document.is_explicit(self.field_path))
        except Exception:
            return False

    def _mode_button_label(self) -> str:
        return "Override…" if self._automatic else "Reset to Automatic"

    def _has_value_to_remove(self) -> bool:
        return self._is_explicit_safe() or bool(self._raw_control_value())

    def _raw_control_value(self) -> str:  # pragma: no cover - overridden
        return ""

    # -- automatic/override toggle -----------------------------------------

    def _apply_mode_visibility(self) -> None:
        if not self.optional:
            return
        try:
            control = self.query_one(f"#control-{self.slug}")
        except Exception:
            return
        control.display = not self._automatic

    def _toggle_mode(self) -> None:
        if self._automatic:
            self._set_automatic(False)
            self._focus_control()
            return
        if self._has_value_to_remove():
            self.app.push_screen(
                ConfirmScreen(
                    "Return to Automatic?",
                    f"Return “{self.label}” to Automatic? "
                    "This removes the persisted value.",
                    confirm_label="Return to Automatic",
                ),
                self._on_confirm_automatic,
            )
        else:
            self._set_automatic(True)

    def _on_confirm_automatic(self, confirmed: bool | None) -> None:
        if confirmed:
            self._set_automatic(True)

    def _set_automatic(self, automatic: bool) -> None:
        self._automatic = automatic
        if automatic:
            # Removing the persisted key is the whole point of Automatic.
            self.document.reset(self.field_path)
        self._apply_mode_visibility()
        try:
            self.query_one(f"#mode-{self.slug}", Button).label = (
                self._mode_button_label()
            )
        except Exception:
            pass
        self.refresh_badge()
        self._notify_changed()

    def _focus_control(self) -> None:  # pragma: no cover - overridden
        return

    # -- badges ------------------------------------------------------------

    def _badge_text(self) -> str:
        if self.optional and self._automatic:
            return BADGE_AUTOMATIC
        return super()._badge_text()

    def refresh_badge(self) -> None:
        super().refresh_badge()
        try:
            badge = self.query_one(f"#badge-{self.slug}", Static)
        except Exception:
            return
        badge.set_class(self.optional and self._automatic, "badge-automatic")

    # -- discovery ---------------------------------------------------------

    def _build_request(self) -> DiscoveryRequest:
        ctx: dict[str, Any] = {}
        if self._context_provider is not None:
            ctx = self._context_provider(self._discovery_kind) or {}
        return DiscoveryRequest(
            kind=self._discovery_kind or DiscoveryKind.VPC_NAME,
            vpc_id=ctx.get("vpc_id"),
            vpc_name=ctx.get("vpc_name"),
            load_balancer_arn=ctx.get("load_balancer_arn"),
            load_balancer_name=ctx.get("load_balancer_name"),
        )

    def _start_discovery(self) -> None:
        if self._discovery is None or self._discovery_kind is None:
            return
        self._set_discovery_status("Loading discovered resources…", "loading")
        self.run_worker(
            self._discovery_worker(self._build_request()),
            exclusive=True,
            group=f"disc-{self.slug}",
        )

    async def _discovery_worker(self, request: DiscoveryRequest) -> None:
        result = await asyncio.to_thread(self._discovery.discover, request)
        self._apply_discovery(result)

    def _apply_discovery(self, result: DiscoveryResult) -> None:
        self._records_by_value = {}
        try:
            select = self.query_one(f"#select-{self.slug}", Select)
        except Exception:
            return
        if not result.ok:
            select.set_options([])
            select.remove_class("picker-visible")
            message = result.failure.message if result.failure else "Lookup failed."
            self._set_discovery_status(f"Lookup failed: {message}", "failure")
            return
        if result.empty:
            select.set_options([])
            select.remove_class("picker-visible")
            self._set_discovery_status("No matching AWS resources found.", "empty")
            return
        options: list[tuple[str, str]] = []
        for record in result.records:
            self._records_by_value[record.value] = record
            options.append((record.label, record.value))
        select.set_options(options)
        select.add_class("picker-visible")
        self._set_discovery_status(
            f"{len(options)} found — choose one to fill the field.", "results"
        )

    def _set_discovery_status(self, text: str, kind: str) -> None:
        try:
            status = self.query_one(f"#discstatus-{self.slug}", Static)
        except Exception:
            return
        status.update(text)
        for cls in ("status-loading", "status-failure", "status-empty", "status-results"):
            status.remove_class(cls)
        status.add_class(f"status-{kind}")
        status.display = True

    def _on_record_selected(self, value: str) -> None:
        record = self._records_by_value.get(value)
        if record is None:
            return
        self._adopt_record(record)
        self.touched = True
        self.post_message(self.RecordSelected(self, record))
        self._reset_verify_status()
        self._notify_changed()

    def _adopt_record(self, record: ResourceRecord) -> None:  # pragma: no cover - overridden
        return

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != f"select-{self.slug}":
            return
        event.stop()
        value = event.value
        if value is None or value is SELECT_BLANK:
            return
        self._on_record_selected(str(value))

    # -- verification ------------------------------------------------------

    def _verify_target(self) -> str:  # pragma: no cover - overridden
        return ""

    def _start_verify(self) -> None:
        if self._discovery is None:
            return
        target = self._verify_target()
        self._set_verify_status(VerificationStatus.NOT_CHECKED, "Verifying…")
        self.run_worker(
            self._verify_worker(self._build_request(), target),
            exclusive=True,
            group=f"verify-{self.slug}",
        )

    async def _verify_worker(self, request: DiscoveryRequest, target: str) -> None:
        outcome = await asyncio.to_thread(self._discovery.verify, request, target)
        self._set_verify_status(outcome.status, outcome.message)

    def _set_verify_status(self, status: VerificationStatus, message: str) -> None:
        if not self._verifiable:
            return
        try:
            widget = self.query_one(f"#verifystatus-{self.slug}", Static)
        except Exception:
            return
        if status is VerificationStatus.VERIFIED:
            text, cls = VERIFY_VERIFIED, "verify-verified"
        elif status is VerificationStatus.FAILED:
            text, cls = VERIFY_FAILED, "verify-failed"
        else:
            text, cls = (message or VERIFY_NOT_CHECKED), "verify-none"
        if message and status is not VerificationStatus.NOT_CHECKED:
            text = f"{text} — {message}"
        widget.update(text)
        for c in ("verify-verified", "verify-failed", "verify-none"):
            widget.remove_class(c)
        widget.add_class(cls)

    def _reset_verify_status(self) -> None:
        if self._verifiable:
            self._set_verify_status(VerificationStatus.NOT_CHECKED, VERIFY_NOT_CHECKED)

    # -- shared composition fragments --------------------------------------

    def _compose_mode_toggle(self):
        if self.optional:
            with Horizontal(classes="mode-row"):
                yield Button(
                    self._mode_button_label(),
                    id=f"mode-{self.slug}",
                    classes="mode-toggle",
                    compact=True,
                )

    def _compose_discovery_actions(self):
        if self._discovery_kind is not None:
            with Horizontal(classes="aws-actions"):
                yield Button(
                    "Select from AWS", id=f"discover-{self.slug}", compact=True
                )
            yield Select(
                [],
                id=f"select-{self.slug}",
                prompt="Discovered resources",
                allow_blank=True,
                classes="aws-select",
            )
            yield Static("", id=f"discstatus-{self.slug}", classes="aws-status")

    def _compose_verify_action(self):
        if self._verifiable:
            with Horizontal(classes="aws-actions"):
                yield Button("Verify", id=f"verify-{self.slug}", compact=True)
                yield Static(
                    VERIFY_NOT_CHECKED,
                    id=f"verifystatus-{self.slug}",
                    classes="verify-status verify-none",
                )

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_mode_visibility()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == f"mode-{self.slug}":
            event.stop()
            self._toggle_mode()
        elif button_id == f"discover-{self.slug}":
            event.stop()
            self._start_discovery()
        elif button_id == f"verify-{self.slug}":
            event.stop()
            self._start_verify()


class AwsReferenceField(AwsBackedField):
    """A scalar reference (id/ARN/name) with manual entry and AWS selection.

    Used for VPC name/id, shared ALB name, shared listener ARN, shared ALB
    security-group id, and the dedicated certificate ARN. Manual entry always
    works; discovery only *offers* values through a picker and never overwrites
    what is typed.
    """

    def _compose_control(self):
        yield from self._compose_mode_toggle()
        with Vertical(id=f"control-{self.slug}", classes="aws-control"):
            value = self.document.value(self.field_path)
            yield Input(
                value="" if value is None else str(value),
                id=f"input-{self.slug}",
                classes="field-input",
            )
            yield from self._compose_discovery_actions()
            yield from self._compose_verify_action()

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def _raw_control_value(self) -> str:
        try:
            return self._input().value.strip()
        except Exception:
            return ""

    def current_value(self) -> str:
        if self.optional and self._automatic:
            return ""
        return self._raw_control_value()

    def _current_key(self) -> Any:
        if self.optional and self._automatic:
            return ("auto",)
        return ("value", self._raw_control_value())

    def commit(self) -> None:
        if not self.is_dirty():
            return
        if self.optional and self._automatic:
            self.document.reset(self.field_path)
            return
        text = self.current_value()
        if text == "":
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, text)

    def _adopt_record(self, record: ResourceRecord) -> None:
        self._input().value = record.value

    def _verify_target(self) -> str:
        return self.current_value()

    def _focus_control(self) -> None:
        try:
            self._input().focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"input-{self.slug}":
            return
        event.stop()
        self._reset_verify_status()
        self._notify_changed()


class AwsSubnetListField(AwsBackedField):
    """An Automatic/Override list of subnet ids with manual entry and AWS multi-select.

    Automatic omits the field so subnets are discovered at deploy time; Override
    persists an explicit list. Discovery offers a multi-select of candidate
    subnets scoped to the chosen VPC; the comma-separated manual entry always
    remains editable.
    """

    def _compose_control(self):
        yield from self._compose_mode_toggle()
        with Vertical(id=f"control-{self.slug}", classes="aws-control"):
            value = self.document.value(self.field_path)
            text = ", ".join(str(item) for item in value) if value else ""
            yield Input(
                value=text,
                id=f"input-{self.slug}",
                classes="field-input",
            )
            if self._discovery_kind is not None:
                with Horizontal(classes="aws-actions"):
                    yield Button(
                        "Discover subnets", id=f"discover-{self.slug}", compact=True
                    )
                yield SelectionList[str](
                    id=f"multiselect-{self.slug}", classes="aws-multiselect"
                )
                yield Static("", id=f"discstatus-{self.slug}", classes="aws-status")

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def _raw_control_value(self) -> str:
        try:
            return self._input().value.strip()
        except Exception:
            return ""

    def current_value(self) -> list[str]:
        if self.optional and self._automatic:
            return []
        raw = self._raw_control_value()
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _current_key(self) -> Any:
        if self.optional and self._automatic:
            return ("auto",)
        return ("value", tuple(self.current_value()))

    def commit(self) -> None:
        if not self.is_dirty():
            return
        if self.optional and self._automatic:
            self.document.reset(self.field_path)
            return
        values = self.current_value()
        if not values:
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, values)

    def _focus_control(self) -> None:
        try:
            self._input().focus()
        except Exception:
            pass

    # Discovery populates a multi-select rather than a single-value Select.
    def _apply_discovery(self, result: DiscoveryResult) -> None:
        try:
            selection = self.query_one(f"#multiselect-{self.slug}", SelectionList)
        except Exception:
            return
        selection.clear_options()
        self._records_by_value = {}
        if not result.ok:
            selection.remove_class("picker-visible")
            message = result.failure.message if result.failure else "Lookup failed."
            self._set_discovery_status(f"Lookup failed: {message}", "failure")
            return
        if result.empty:
            selection.remove_class("picker-visible")
            self._set_discovery_status("No matching AWS resources found.", "empty")
            return
        current = set(self.current_value())
        for record in result.records:
            self._records_by_value[record.value] = record
            selection.add_option((record.label, record.value, record.value in current))
        selection.add_class("picker-visible")
        self._set_discovery_status(
            f"{len(result.records)} found — tick subnets to use them.", "results"
        )

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if event.selection_list.id != f"multiselect-{self.slug}":
            return
        event.stop()
        selected = [str(v) for v in event.selection_list.selected]
        self._input().value = ", ".join(selected)
        self.touched = True
        self._notify_changed()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"input-{self.slug}":
            return
        event.stop()
        self._notify_changed()


class OptionalSelectField(AwsBackedField):
    """An Automatic/Override dropdown for an omittable, deploy-derived setting.

    Automatic omits the field entirely (preserving any downstream inference, for
    example architecture detection from the instance type); Override persists an
    explicit choice from a fixed option set. Returning an existing Override to
    Automatic asks for confirmation before removing the persisted value. There is
    no AWS discovery: the value comes from a fixed enumeration.
    """

    def __init__(self, *, options: list[tuple[str, str]], **kwargs: Any) -> None:
        kwargs.setdefault("optional", True)
        super().__init__(**kwargs)
        self._options = options

    def _compose_control(self):
        yield from self._compose_mode_toggle()
        with Vertical(id=f"control-{self.slug}", classes="aws-control"):
            value = self.document.value(self.field_path)
            current = None if value is None else str(value)
            yield Select(
                self._options,
                value=current if current is not None else SELECT_BLANK,
                allow_blank=True,
                id=f"input-{self.slug}",
                classes="field-select",
            )

    def _select_control(self) -> Select:
        return self.query_one(f"#input-{self.slug}", Select)

    def _raw_control_value(self) -> str:
        try:
            value = self._select_control().value
        except Exception:
            return ""
        return "" if value is SELECT_BLANK else str(value)

    def current_value(self) -> str | None:
        if self.optional and self._automatic:
            return None
        raw = self._raw_control_value()
        return raw or None

    def _current_key(self) -> Any:
        if self.optional and self._automatic:
            return ("auto",)
        return ("value", self._raw_control_value())

    def commit(self) -> None:
        if not self.is_dirty():
            return
        if self.optional and self._automatic:
            self.document.reset(self.field_path)
            return
        value = self.current_value()
        if value is None:
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, value)

    def _focus_control(self) -> None:
        try:
            self._select_control().focus()
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != f"input-{self.slug}":
            return
        event.stop()
        self._notify_changed()


class OptionalIntegerField(AwsBackedField):
    """An Automatic/Override integer for an omittable, deploy-derived value.

    Automatic omits the field so deployment allocates the value; Override
    persists an explicit integer. Returning an existing Override to Automatic
    asks for confirmation before removing the persisted value. Used for ALB
    listener priorities, which remain *preferred* overrides while deploy-time
    allocation stays authoritative and stack-owned values are preserved. There is
    no AWS discovery: the value is a plain integer, never a looked-up resource.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("optional", True)
        super().__init__(**kwargs)

    def _compose_control(self):
        yield from self._compose_mode_toggle()
        with Vertical(id=f"control-{self.slug}", classes="aws-control"):
            value = self._loaded_value()
            yield Input(
                value="" if value is None else str(value),
                id=f"input-{self.slug}",
                classes="field-input",
            )

    def _input(self) -> Input:
        return self.query_one(f"#input-{self.slug}", Input)

    def _raw_control_value(self) -> str:
        try:
            return self._input().value.strip()
        except Exception:
            return ""

    def current_value(self) -> int | None:
        if self.optional and self._automatic:
            return None
        raw = self._raw_control_value()
        if raw == "":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _current_key(self) -> Any:
        if self.optional and self._automatic:
            return ("auto",)
        return ("value", self._raw_control_value())

    def validation_error(self) -> str | None:
        if self.optional and self._automatic:
            return None
        raw = self._raw_control_value()
        if raw == "":
            return None
        try:
            int(raw)
        except ValueError:
            return f"{self.label} must be a whole number"
        return None

    def commit(self) -> None:
        if not self.is_dirty():
            return
        if self.optional and self._automatic:
            self.document.reset(self.field_path)
            return
        raw = self._raw_control_value()
        if raw == "":
            self.document.reset(self.field_path)
            return
        try:
            self.document.set(self.field_path, int(raw))
        except ValueError:
            # Malformed input is surfaced by validation_error; do not corrupt the
            # draft with a non-integer value.
            return

    def _focus_control(self) -> None:
        try:
            self._input().focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"input-{self.slug}":
            return
        event.stop()
        self._notify_changed()


class ServiceSelectField(EditableField):
    """A dropdown bound to a scalar service-name field.

    Lists only the services eligible as a routing target (the caller supplies the
    eligible names according to the existing model rules) plus the currently
    persisted value when it is set — so an existing reference round-trips and can
    be corrected rather than crashing the control. Selecting the blank option
    removes the key.
    """

    def __init__(self, *, eligible: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._eligible = list(eligible)

    def _option_names(self) -> list[str]:
        names = list(self._eligible)
        value = self._loaded_value()
        if value not in (None, "") and str(value) not in names:
            names.append(str(value))
        return names

    def _compose_control(self):
        value = self._loaded_value()
        current = None if value in (None, "") else str(value)
        yield Select(
            [(name, name) for name in self._option_names()],
            value=current if current is not None else SELECT_BLANK,
            allow_blank=True,
            id=f"input-{self.slug}",
            classes="field-select",
        )

    def _select(self) -> Select:
        return self.query_one(f"#input-{self.slug}", Select)

    def current_value(self) -> str | None:
        value = self._select().value
        if value is SELECT_BLANK:
            return None
        return str(value)

    def _current_key(self) -> Any:
        return self.current_value()

    def commit(self) -> None:
        if not self.is_dirty():
            return
        value = self.current_value()
        if value is None:
            self.document.reset(self.field_path)
        else:
            self.document.set(self.field_path, value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != f"input-{self.slug}":
            return
        event.stop()
        self._notify_changed()


__all__ = [
    "dom_slug",
    "EditableField",
    "TextField",
    "TextAreaField",
    "IntegerField",
    "BooleanField",
    "SelectField",
    "StringListField",
    "KeyValueMapField",
    "MultiSelectField",
    "ReadOnlyField",
    "AwsReferenceField",
    "AwsSubnetListField",
    "OptionalSelectField",
    "OptionalIntegerField",
    "ServiceSelectField",
]
