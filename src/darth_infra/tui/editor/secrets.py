"""The Secrets section: a master-detail editor for secret declarations (ticket 12).

Secrets are a repeatable resource, so this section reuses
:class:`MasterDetailSection` exactly like Services and Storage: a searchable list
of secrets beside :class:`SecretDetail`, the editor for the selected secret, with
Add, Duplicate, and confirmed Delete. Together they cover every persisted secret
field — the environment-variable name, the source, the existing secret name/ARN
or RDS JSON key, the generated length, and ``generate_once`` — plus the reverse
view of service bindings, editing the document draft directly.

The four supported sources keep their existing deploy semantics:

* ``generate`` auto-creates a random value per environment (``length`` and
  ``generate_once`` apply);
* ``env`` imports a secret whose name/ARN the *deployer's local environment*
  provides — the TUI describes that reference but never collects or persists it;
* ``existing`` references an existing Secrets Manager secret by name/ARN, which
  can be *selected* through the injected AWS discovery adapter (identifiers and
  metadata only) or typed manually offline;
* ``rds`` reads a JSON key from the database-provided secret, preserving existing
  RDS binding behavior and JSON-key validation.

Source-specific fields live in conditional panels. Switching to a source
incompatible with a currently-set existing name/ARN asks for confirmation and
only then clears it, so a value is never silently discarded.

This editor never retrieves, reveals, or renders a secret *value*: it calls no
``get_secret_value``, discovery lists names/ARNs only, and no value is ever
written to logs, errors, or test snapshots. Ordinary service environment
variables are edited under Services and are deliberately out of this screen.

Deleting a secret that services still inject is not blocked: Delete presents the
complete impact — every service ``secrets`` binding that names it — and, on
confirmation, removes the declaration and every binding to it in one reversible
document transaction. The impact inventory and cleanup live in the widget-free
:mod:`darth_infra.config.reference_impact` module.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Checkbox, Collapsible, Input, SelectionList, Static

from ...config.reference_impact import (
    remove_secret_with_references,
    secret_removal_references,
)
from ..field_registry import registry_entry
from .aws_discovery import AwsDiscovery, DiscoveryKind, OfflineAwsDiscovery
from .collection import (
    STATE_INVALID,
    STATE_MODIFIED,
    STATE_OK,
    ConfirmScreen,
    MasterDetailSection,
)
from .widgets import (
    SELECT_BLANK,
    AwsReferenceField,
    BooleanField,
    EditableField,
    IntegerField,
    TextField,
    dom_slug,
)

_COLLECTION = "secrets"

_SOURCE_OPTIONS = [
    ("Generate a random value per environment", "generate"),
    ("Import from the deployer's local environment", "env"),
    ("Reference an existing Secrets Manager secret", "existing"),
    ("Read a JSON key from the RDS-provided secret", "rds"),
]

# Advanced (collapsible) fields, meaningful only for the generate source.
_ADVANCED_FIELDS = ("length", "generate_once")

_ENV_NOTE = (
    "The 'env' source imports a secret whose name/ARN the deployer supplies "
    "through their own local environment variable at deploy time. That reference "
    "is not collected or stored here, and its value is never shown."
)


def _secret_help(field: str) -> str:
    entry = registry_entry(f"secrets[].{field}")
    return entry.help if entry else ""


def _secret_example(field: str) -> str | None:
    entry = registry_entry(f"secrets[].{field}")
    return entry.example if entry else None


class SecretBindingsField(EditableField):
    """Choose which services inject this secret (the reverse of ``services[].secrets``).

    The persisted binding lives on each service's ``secrets`` list; this control
    presents the reverse view so one declaration can be bound to several services
    from the Secrets editor. Toggling a service is reconciled into the document on
    commit using the secret's *current* name, so a rename made in the same edit
    still lands on the right services. The secret's value is never involved.
    """

    def __init__(
        self,
        *,
        services: list[tuple[int, str]],
        name_provider: Callable[[], str],
        original_name: str,
        empty_message: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._services = list(services)
        self._name_provider = name_provider
        self._original_name = original_name
        self._empty_message = empty_message

    def _bound_indices(self) -> set[int]:
        bound: set[int] = set()
        if not self._original_name:
            return bound
        for j, _name in self._services:
            secrets = self.document.raw_record("services", j).get("secrets") or []
            if self._original_name in secrets:
                bound.add(j)
        return bound

    def _compose_control(self):
        yield Static(
            self._empty_message, id=f"empty-{self.slug}", classes="field-help"
        )
        current = self._bound_indices()
        yield SelectionList[str](
            *[(name, str(j), j in current) for j, name in self._services],
            id=f"input-{self.slug}",
            classes="aws-multiselect",
        )

    def on_mount(self) -> None:
        super().on_mount()
        has_services = bool(self._services)
        self.query_one(f"#empty-{self.slug}", Static).display = not has_services
        self.query_one(f"#input-{self.slug}", SelectionList).display = has_services

    def _selection(self) -> SelectionList:
        return self.query_one(f"#input-{self.slug}", SelectionList)

    def current_value(self) -> list[int]:
        selected = {int(v) for v in self._selection().selected}
        return [j for j, _name in self._services if j in selected]

    def _current_key(self) -> Any:
        return tuple(self.current_value())

    # Bindings are not one persisted key, so the explicit/default badge is moot.
    def _badge_text(self) -> str:
        return ""

    def refresh_badge(self) -> None:
        try:
            self.query_one(f"#badge-{self.slug}", Static).update("")
        except Exception:
            pass

    def commit(self) -> None:
        # Always reconcile (idempotent): a rename with an unchanged selection
        # still needs the old name swapped for the new one on every service.
        name = (self._name_provider() or "").strip()
        selected = set(self.current_value())
        for j, _svc in self._services:
            current = list(self.document.raw_record("services", j).get("secrets") or [])
            cleaned = [s for s in current if s not in (self._original_name, name)]
            if j in selected and name:
                cleaned.append(name)
            if cleaned == current:
                continue
            if cleaned:
                self.document.set(f"services[{j}].secrets", cleaned)
            else:
                self.document.reset(f"services[{j}].secrets")

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if event.selection_list.id != f"input-{self.slug}":
            return
        event.stop()
        self.touched = True
        self._notify_changed()


class _SourceSelectField(EditableField):
    """A dropdown for the secret source.

    A dedicated subclass (rather than the shared ``SelectField``) so a source
    change is intercepted by :class:`SecretDetail` before it commits, letting a
    switch that would clear an incompatible existing name/ARN be confirmed or
    reverted.
    """

    def __init__(self, *, options: list[tuple[str, str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._options = options

    def _compose_control(self):
        from textual.widgets import Select

        value = self.document.value(self.field_path)
        current = None if value is None else str(value)
        yield Select(
            self._options,
            value=current if current is not None else SELECT_BLANK,
            allow_blank=False,
            id=f"input-{self.slug}",
            classes="field-select",
        )

    def _select(self):
        from textual.widgets import Select

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

    def on_select_changed(self, event: Any) -> None:
        if event.select.id != f"input-{self.slug}":
            return
        event.stop()
        self._notify_changed()


class _ExistingSecretField(AwsReferenceField):
    """The existing secret name/ARN (or RDS JSON key), with optional AWS selection.

    Manual entry always works. In ``existing`` mode a "Select from AWS" picker
    lists Secrets Manager identifiers/metadata only; in ``rds`` mode the value is
    a JSON key, so the discovery controls are hidden as they do not apply.
    """

    def set_discovery_visible(self, visible: bool) -> None:
        for selector in (
            f"#discover-{self.slug}",
            f"#select-{self.slug}",
            f"#discstatus-{self.slug}",
        ):
            try:
                self.query_one(selector).display = visible
            except Exception:
                pass


class SecretDetail(Vertical):
    """Editor for a single secret, bound to ``secrets[<index>]`` paths."""

    class DraftChanged(Message):
        """Posted when a field edit changes the secret draft."""

    def __init__(
        self, document: Any, index: int, discovery: AwsDiscovery
    ) -> None:
        super().__init__(id=f"secret-detail-{index}", classes="detail-form")
        self.document = document
        self.index = index
        self._discovery = discovery
        # The name the secret loaded with, used to reconcile service bindings
        # across a rename in the same edit session.
        self._original_name = str(
            self.document.raw_record(_COLLECTION, index).get("name") or ""
        )
        self._committed_source = self._source_value()
        self._reverting_source = False

    def _path(self, field: str) -> str:
        return f"{_COLLECTION}[{self.index}].{field}"

    def _source_value(self) -> str:
        try:
            value = self.document.value(self._path("source"))
        except Exception:
            value = None
        return str(value) if value else "generate"

    # -- services (for bindings) -------------------------------------------

    def _services(self) -> list[tuple[int, str]]:
        services: list[tuple[int, str]] = []
        try:
            count = self.document.record_count("services")
        except Exception:
            return services
        for j in range(count):
            try:
                raw = self.document.raw_record("services", j)
            except Exception:
                continue
            name = str(raw.get("name") or "").strip()
            if name:
                services.append((j, name))
        return services

    def _current_secret_name(self) -> str:
        field = self._field("name")
        if field is not None:
            return str(field.current_value() or "")
        return self._original_name

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="secret-detail-error", classes="field-error")

        yield TextField(
            field_path=self._path("name"),
            document=self.document,
            label="Environment variable name",
            help=_secret_help("name"),
            constraints="required; unique across secrets",
            example=_secret_example("name"),
            required=True,
        )
        yield _SourceSelectField(
            field_path=self._path("source"),
            document=self.document,
            label="Source",
            help=_secret_help("source"),
            default_display="generate",
            options=_SOURCE_OPTIONS,
        )
        yield _ExistingSecretField(
            field_path=self._path("existing_secret_name"),
            document=self.document,
            label="Existing secret name/ARN or RDS JSON key",
            help=_secret_help("existing_secret_name"),
            constraints="required for existing and rds sources",
            example=_secret_example("existing_secret_name"),
            discovery=self._discovery,
            discovery_kind=DiscoveryKind.SECRET,
        )
        yield Static(
            _ENV_NOTE, id=f"secret-env-note-{self.index}", classes="field-help"
        )

        yield SecretBindingsField(
            field_path=self._path("__bindings__"),
            document=self.document,
            label="Bound services",
            help=(
                "Services that inject this secret as an environment variable. "
                "Editing this updates each service's secrets list."
            ),
            services=self._services(),
            name_provider=self._current_secret_name,
            original_name=self._original_name,
            empty_message="No services yet. Add services first, then bind this secret.",
        )

        yield Collapsible(
            *self._advanced_widgets(),
            title=self._advanced_title(),
            id=f"advanced-secret-{self.index}",
            collapsed=not self._advanced_should_expand(),
        )

    def _advanced_widgets(self) -> list[EditableField]:
        return [
            IntegerField(
                field_path=self._path("length"),
                document=self.document,
                label="Generated length",
                help=_secret_help("length"),
                default_display="50",
                constraints="must be >= 1",
            ),
            BooleanField(
                field_path=self._path("generate_once"),
                document=self.document,
                label="Generate once and reuse",
                help=_secret_help("generate_once"),
                default_display="true",
            ),
        ]

    def on_mount(self) -> None:
        for field in self._fields():
            field.refresh_badge()
        self._committed_source = self._current_source()
        self._apply_conditionals()
        self._show_banner(None)

    # -- field access ------------------------------------------------------

    def _fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def _field(self, field: str) -> EditableField | None:
        try:
            return self.query_one(
                f"#field-{dom_slug(self._path(field))}", EditableField
            )
        except Exception:
            return None

    def focus_first(self) -> None:
        field = self._field("name")
        if field is not None:
            inputs = field.query(Input)
            if inputs:
                inputs.first().focus()

    # -- conditional presentation ------------------------------------------

    def _current_source(self) -> str:
        field = self._field("source")
        if field is not None:
            value = field.current_value()
            if value:
                return str(value)
        return "generate"

    def _apply_conditionals(self) -> None:
        source = self._current_source()
        existing = self._field("existing_secret_name")
        if existing is not None:
            existing.display = source in ("existing", "rds")
            if isinstance(existing, _ExistingSecretField):
                existing.set_discovery_visible(source == "existing")
        try:
            note = self.query_one(f"#secret-env-note-{self.index}", Static)
            note.display = source == "env"
        except Exception:
            pass
        try:
            advanced = self.query_one(f"#advanced-secret-{self.index}", Collapsible)
            advanced.display = source == "generate"
        except Exception:
            pass

    # -- source change with confirmation -----------------------------------

    def _field_has_value(self, name: str) -> bool:
        field = self._field(name)
        if field is None:
            return False
        value = field.current_value()
        if isinstance(value, bool):
            return value
        return bool(value)

    def _incompatible_for_source(self, source: str) -> list[str]:
        # generate/env forbid an existing name/ARN; existing/rds require one, so
        # switching to them clears nothing.
        if source in ("generate", "env") and self._field_has_value(
            "existing_secret_name"
        ):
            return ["existing_secret_name"]
        return []

    _FIELD_LABELS = {
        "existing_secret_name": "existing secret name/ARN or RDS JSON key",
    }

    def _handle_source_change(self, source_field: EditableField) -> None:
        if self._reverting_source:
            self._reverting_source = False
            return
        new_source = source_field.current_value() or "generate"
        if new_source == self._committed_source:
            source_field.commit()
            return
        incompatible = self._incompatible_for_source(str(new_source))
        if not incompatible:
            self._adopt_source(source_field, str(new_source), [])
            return

        cleared = ", ".join(self._FIELD_LABELS[name] for name in incompatible)

        def _after(confirmed: bool | None) -> None:
            if confirmed:
                self._adopt_source(source_field, str(new_source), incompatible)
            else:
                self._revert_source(source_field)

        self.app.push_screen(
            ConfirmScreen(
                "Change secret source?",
                f"Switching to '{new_source}' will clear: {cleared}. Continue?",
                confirm_label="Change source",
                confirm_variant="warning",
            ),
            _after,
        )

    def _adopt_source(
        self, source_field: EditableField, new_source: str, incompatible: list[str]
    ) -> None:
        source_field.commit()
        for name in incompatible:
            self._clear_field(name)
        self._committed_source = new_source
        self._apply_conditionals()
        self._sync_touched_errors()
        self.post_message(self.DraftChanged())

    def _revert_source(self, source_field: EditableField) -> None:
        self._reverting_source = True
        for select in source_field.query("Select"):
            try:
                select.value = self._committed_source
            except Exception:
                pass
            break
        else:
            self._reverting_source = False

    def _clear_field(self, name: str) -> None:
        field = self._field(name)
        if field is None:
            return
        self.document.reset(field.field_path)
        for inp in field.query(Input):
            inp.value = ""
        for checkbox in field.query(Checkbox):
            checkbox.value = False
        field.mark_committed()
        field.refresh_badge()

    # -- advanced panel ----------------------------------------------------

    def _advanced_configured_count(self) -> int:
        count = 0
        for name in _ADVANCED_FIELDS:
            try:
                if self.document.is_explicit(self._path(name)):
                    count += 1
            except Exception:
                pass
        return count

    def _advanced_title(self) -> str:
        return f"Advanced ({self._advanced_configured_count()} configured)"

    def _advanced_has_error(self) -> bool:
        return any(
            (f := self._field(name)) is not None and f.error
            for name in _ADVANCED_FIELDS
        )

    def _advanced_should_expand(self) -> bool:
        return self._advanced_configured_count() > 0 or self._advanced_has_error()

    def _refresh_advanced(self) -> None:
        try:
            panel = self.query_one(f"#advanced-secret-{self.index}", Collapsible)
        except Exception:
            return
        panel.title = self._advanced_title()
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def commit_all(self) -> None:
        for field in self._fields():
            field.commit()

    def _sibling_names(self) -> list[str]:
        names: list[str] = []
        for i in range(self.document.record_count(_COLLECTION)):
            if i == self.index:
                continue
            names.append(str(self.document.raw_record(_COLLECTION, i).get("name", "")))
        return names

    def _field_errors(self) -> dict[str, str]:
        self.commit_all()
        errors: dict[str, str] = {}

        name_field = self._field("name")
        name = name_field.current_value() if name_field else ""
        if not name:
            errors[self._path("name")] = "Environment variable name is required"
        elif name in self._sibling_names():
            errors[self._path("name")] = "Secret name must be unique"

        source = self._current_source()
        if source in ("existing", "rds") and not self._field_has_value(
            "existing_secret_name"
        ):
            label = (
                "Existing secret name/ARN"
                if source == "existing"
                else "RDS JSON key"
            )
            errors[self._path("existing_secret_name")] = f"{label} is required"

        for field in self._fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            mentions_this = bool(name) and f"'{name}'" in error
            if mentions_this and "existing_secret_name" in lowered:
                errors.setdefault(self._path("existing_secret_name"), error)
            elif mentions_this and "generate_once" in lowered:
                errors.setdefault(self._path("generate_once"), error)
            elif "references unknown secret" in lowered:
                errors.setdefault(self._path("__bindings__"), error)
            else:
                errors.setdefault("__section__", error)
        return errors

    def _sync_touched_errors(self) -> None:
        errors = self._field_errors()
        for field in self._fields():
            if field.touched:
                message = errors.get(field.field_path)
                if message:
                    field.show_error(message)
                else:
                    field.clear_error()
            field.refresh_badge()
        self._show_banner(errors.get("__section__"))
        self._refresh_advanced()

    def validate_for_save(self) -> list[Any]:
        errors = self._field_errors()
        invalid: list[Any] = []
        for field in self._fields():
            message = errors.get(field.field_path)
            if message:
                field.touched = True
                field.show_error(message)
                invalid.append(field)
            elif field.touched:
                field.clear_error()
            field.refresh_badge()
        self._show_banner(errors.get("__section__"))
        self._refresh_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._fields():
            field.mark_committed()
            field.refresh_badge()
        self._refresh_advanced()

    def _show_banner(self, message: str | None) -> None:
        banner = self.query_one("#secret-detail-error", Static)
        if message:
            banner.update(f"✗ {message}")
            banner.display = True
        else:
            banner.update("")
            banner.display = False

    # -- events ------------------------------------------------------------

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        if event.field.field_path == self._path("source"):
            self._handle_source_change(event.field)
            return
        event.field.commit()
        self._apply_conditionals()
        self._sync_touched_errors()
        self.post_message(self.DraftChanged())

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()


class SecretsSection(MasterDetailSection):
    """Searchable master-detail editor for the project's secret declarations."""

    section_title = "Secrets"
    item_noun = "secret"
    empty_message = "No secrets yet. Add one to get started."

    def __init__(self, document: Any, discovery: AwsDiscovery | None = None) -> None:
        super().__init__(document)
        self._discovery = discovery or OfflineAwsDiscovery()
        self._modified: set[int] = set()

    # -- record metadata ---------------------------------------------------

    def item_count(self) -> int:
        return self.document.record_count(_COLLECTION)

    def _record_name(self, index: int) -> str:
        return str(self.document.raw_record(_COLLECTION, index).get("name", ""))

    def item_label(self, index: int) -> str:
        name = self._record_name(index)
        return name if name else "(unnamed secret)"

    def item_state(self, index: int) -> str:
        name = self._record_name(index)
        names = [self._record_name(i) for i in range(self.item_count())]
        if not name or names.count(name) > 1:
            return STATE_INVALID
        if index in self._modified:
            return STATE_MODIFIED
        return STATE_OK

    def build_detail(self, index: int) -> SecretDetail:
        return SecretDetail(self.document, index, self._discovery)

    # -- add / duplicate / delete ------------------------------------------

    def create_record(self) -> int:
        return self.document.add_record(_COLLECTION, {"name": ""})

    def duplicate_record(self, index: int) -> int:
        values = self.document.raw_record(_COLLECTION, index)
        values["name"] = ""
        return self.document.add_record(_COLLECTION, values)

    def delete_record(self, index: int) -> None:
        self.document.remove_record(_COLLECTION, index)
        self._reindex_after_delete(index)

    def cascade_delete(self, index: int) -> None:
        name = self._record_name(index)
        # One document transaction: the secret and every service binding to it go
        # together, so the whole cascade reverts as a unit until it is saved.
        with self.document.transaction():
            remove_secret_with_references(self.document, name)
        self._reindex_after_delete(index)

    def _reindex_after_delete(self, index: int) -> None:
        self._modified = {
            (i if i < index else i - 1)
            for i in self._modified
            if i != index
        }

    def blocking_references(self, index: int) -> list[str]:
        # A draft that will not parse cannot be scanned for references; block the
        # delete rather than risk leaving a dangling binding.
        try:
            self.document.config
        except Exception:
            return ["the configuration has errors elsewhere; resolve them first"]
        return []

    def reference_impact(self, index: int) -> list[str]:
        name = self._record_name(index)
        if not name:
            return []
        try:
            config = self.document.config
        except Exception:
            return []
        return [ref.description for ref in secret_removal_references(config, name)]

    # -- modified tracking -------------------------------------------------

    def after_save(self) -> None:
        self._modified.clear()
        super().after_save()

    def on_secret_detail_draft_changed(
        self, event: SecretDetail.DraftChanged
    ) -> None:
        event.stop()
        if self._selected is not None:
            self._modified.add(self._selected)
        self._refresh_list()


__all__ = ["SecretsSection", "SecretDetail", "SecretBindingsField"]
