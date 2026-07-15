"""The Database section: the singleton RDS PostgreSQL editor.

RDS is a single optional resource, not a repeatable collection, so this section
is a singleton editor (like Network) rather than a master-detail one. It covers
every persisted RDS field — database name, instance type, allocated storage, and
exposed services as common fields, plus engine version and backup retention as
Advanced fields that auto-expand when configured or invalid — editing the
document draft directly.

Enabling RDS creates the ``[rds]`` table; the derived ``DATABASE_*`` /
``POSTGRES_*`` connection environment variables that exposed services receive are
provided by existing RDS semantics in the render context and are shown read-only
here for inspection (never their values). This section does not redesign those
bindings or add new aliases.

Removing RDS is a confirmed, reversible document transaction: it presents the
complete impact (exposed-service env vars, RDS-backed secret declarations and
their service bindings, and per-environment RDS instance-type overrides) and, on
confirmation, drops the database and every dependent reference together. The
impact inventory and cleanup live in the widget-free
:mod:`darth_infra.config.reference_impact` module. Environment-specific RDS
instance-type override *editing* stays in the Environments section; Database only
shows which environments currently override the base value.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Static

from ...config.reference_impact import (
    rds_removal_references,
    remove_rds_with_references,
)
from ..field_registry import registry_entry
from .collection import ConfirmScreen, ImpactConfirmScreen
from .widgets import (
    EditableField,
    IntegerField,
    MultiSelectField,
    TextField,
)

# The connection environment variables exposed services receive from existing
# RDS semantics (mirrors the render-context derivation). Names only: their values
# are managed secret material and are never fetched or displayed here.
_RDS_ENV_VARS = (
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_DB",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

# Advanced (collapsible) paths owned by this section.
_ADVANCED_PATHS = ("rds.engine_version", "rds.backup_retention_days")


def _help(path: str) -> str:
    entry = registry_entry(path)
    return entry.help if entry else ""


def _example(path: str) -> str | None:
    entry = registry_entry(path)
    return entry.example if entry else None


class DatabaseSection(VerticalScroll):
    """Editor for the optional singleton RDS PostgreSQL database."""

    class SaveContinueRequested(Message):
        """Posted when the section's Save & Continue action is pressed."""

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document
        self._enabled = self._rds_present()

    # -- state -------------------------------------------------------------

    def _rds_present(self) -> bool:
        try:
            return bool(self.document.is_explicit("rds"))
        except Exception:
            return False

    def _service_names(self) -> list[str]:
        names: list[str] = []
        try:
            count = self.document.record_count("services")
        except Exception:
            return names
        for index in range(count):
            try:
                raw = self.document.raw_record("services", index)
            except Exception:
                continue
            name = str(raw.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Database", classes="section-title")
        yield Static("", id="section-error", classes="field-error")

        # Disabled state: an empty state and the enable action.
        yield Static(
            "No database configured. RDS PostgreSQL is optional.",
            id="rds-empty",
            classes="field-help",
        )
        yield Button(
            "Enable RDS PostgreSQL", id="rds-enable", variant="success"
        )

        # Enabled state: the full field set.
        yield TextField(
            field_path="rds.database_name",
            document=self.document,
            label="Database name",
            help=_help("rds.database_name"),
            constraints="required; letters, numbers, and underscores; <= 63 chars",
            example="appdb",
            required=True,
        )
        yield TextField(
            field_path="rds.instance_type",
            document=self.document,
            label="Instance type",
            help=_help("rds.instance_type"),
            default_display="db.t4g.micro",
            constraints="normalized to include the required 'db.' prefix",
            example=_example("rds.instance_type"),
        )
        yield IntegerField(
            field_path="rds.allocated_storage_gb",
            document=self.document,
            label="Allocated storage (GB)",
            help=_help("rds.allocated_storage_gb"),
            default_display="20",
            constraints="must be >= 20",
        )
        yield MultiSelectField(
            field_path="rds.expose_to",
            document=self.document,
            label="Exposed services",
            help=_help("rds.expose_to"),
            options=self._service_names(),
            empty_message="No services yet. Add services first, then expose them.",
        )
        yield Static(
            "Exposed services receive these connection environment variables "
            "(managed by existing RDS behavior; values are never shown): "
            + ", ".join(_RDS_ENV_VARS),
            id="rds-envvars",
            classes="field-help",
        )
        yield Static(
            self._env_override_text(),
            id="rds-env-overrides",
            classes="field-help",
        )

        yield Collapsible(
            *self._advanced_widgets(),
            title=self._advanced_title(),
            id="advanced-database",
            collapsed=not self._advanced_should_expand(),
        )

        yield Button("Remove database", id="rds-remove", variant="error")
        yield Button("Save & Continue", id="save-continue", variant="primary")

    def _advanced_widgets(self) -> list[EditableField]:
        return [
            TextField(
                field_path="rds.engine_version",
                document=self.document,
                label="Engine version",
                help=_help("rds.engine_version"),
                default_display="15",
                example=_example("rds.engine_version"),
            ),
            IntegerField(
                field_path="rds.backup_retention_days",
                document=self.document,
                label="Backup retention (days)",
                help=_help("rds.backup_retention_days"),
                default_display="7",
            ),
        ]

    def on_mount(self) -> None:
        for field in self._editable_fields():
            field.refresh_badge()
        self._apply_enabled_visibility()
        self._show_section_error(None)

    # -- field access ------------------------------------------------------

    def _editable_fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def _field(self, path: str) -> EditableField | None:
        for field in self._editable_fields():
            if field.field_path == path:
                return field
        return None

    # -- enable / disable visibility ---------------------------------------

    # Widgets shown only when a database is configured.
    _ENABLED_ONLY = (
        "#rds-envvars",
        "#rds-env-overrides",
        "#advanced-database",
        "#rds-remove",
        "#save-continue",
    )
    # Widgets shown only when no database is configured.
    _DISABLED_ONLY = ("#rds-empty", "#rds-enable")

    def _apply_enabled_visibility(self) -> None:
        for field in self._editable_fields():
            field.display = self._enabled
        for selector in self._ENABLED_ONLY:
            self.query_one(selector).display = self._enabled
        for selector in self._DISABLED_ONLY:
            self.query_one(selector).display = not self._enabled

    # -- environment override display --------------------------------------

    def _env_override_text(self) -> str:
        try:
            config = self.document.config
            overrides = [
                env
                for env, override in config.environment_overrides.items()
                if override.instance_type_override is not None
            ]
        except Exception:
            overrides = []
        if not overrides:
            return (
                "No environments override the base instance type. "
                "Environment-specific overrides are edited in Environments."
            )
        return (
            "Environments overriding the base instance type: "
            + ", ".join(sorted(overrides))
            + ". Edit these in the Environments section."
        )

    # -- advanced panel ----------------------------------------------------

    def _advanced_configured_count(self) -> int:
        count = 0
        for path in _ADVANCED_PATHS:
            try:
                if self.document.is_explicit(path):
                    count += 1
            except Exception:
                pass
        return count

    def _advanced_has_error(self) -> bool:
        return any(
            (f := self._field(path)) is not None and f.error
            for path in _ADVANCED_PATHS
        )

    def _advanced_title(self) -> str:
        return f"Advanced ({self._advanced_configured_count()} configured)"

    def _advanced_should_expand(self) -> bool:
        return self._advanced_configured_count() > 0 or self._advanced_has_error()

    def _refresh_advanced(self) -> None:
        try:
            panel = self.query_one("#advanced-database", Collapsible)
        except Exception:
            return
        panel.title = self._advanced_title()
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_all(self) -> None:
        if not self._enabled:
            return
        for field in self._editable_fields():
            field.commit()

    def _field_errors(self) -> dict[str, str]:
        if not self._enabled:
            return {}
        self._commit_all()
        errors: dict[str, str] = {}

        # Field-level required check first: a clearer message than the raw model
        # error for a missing database name.
        name_field = self._field("rds.database_name")
        if name_field is not None and not name_field.current_value():
            errors["rds.database_name"] = "Database name is required"

        for field in self._editable_fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            if "database_name" in lowered:
                errors.setdefault("rds.database_name", error)
            elif "allocated_storage" in lowered:
                errors.setdefault("rds.allocated_storage_gb", error)
            elif "instance_type" in lowered:
                errors.setdefault("rds.instance_type", error)
            elif "expose_to" in lowered:
                errors.setdefault("rds.expose_to", error)
            else:
                errors.setdefault("__section__", error)
        return errors

    def _sync_touched_errors(self) -> None:
        errors = self._field_errors()
        for field in self._editable_fields():
            if field.touched:
                message = errors.get(field.field_path)
                if message:
                    field.show_error(message)
                else:
                    field.clear_error()
            field.refresh_badge()
        self._show_section_error(errors.get("__section__"))
        self._refresh_advanced()

    def validate_all(self) -> list[EditableField]:
        errors = self._field_errors()
        invalid: list[EditableField] = []
        for field in self._editable_fields():
            message = errors.get(field.field_path)
            if message:
                field.touched = True
                field.show_error(message)
                invalid.append(field)
            elif field.touched:
                field.clear_error()
            field.refresh_badge()
        self._show_section_error(errors.get("__section__"))
        self._refresh_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._editable_fields():
            field.mark_committed()
            field.refresh_badge()
        self._refresh_advanced()

    def _show_section_error(self, message: str | None) -> None:
        banner = self.query_one("#section-error", Static)
        if message:
            banner.update(f"✗ {message}")
            banner.display = True
        else:
            banner.update("")
            banner.display = False

    # -- enable / remove ---------------------------------------------------

    def _enable(self) -> None:
        self._enabled = True
        # Create the [rds] table so the enabled state is a document fact. An
        # empty database name is invalid, so the required check forces the user
        # to name it before a save can succeed.
        if not self._rds_present():
            self.document.set("rds.database_name", "")
        self._apply_enabled_visibility()
        for field in self._editable_fields():
            field.refresh_badge()
        name_field = self._field("rds.database_name")
        if name_field is not None:
            from textual.widgets import Input

            inputs = name_field.query(Input)
            if inputs:
                inputs.first().focus()

    def _handle_remove(self) -> None:
        label = str(self.document.value("rds.database_name") or "database")
        try:
            impact = [
                ref.description
                for ref in rds_removal_references(self.document.config)
            ]
        except Exception:
            impact = []

        if impact:
            def _after_impact(confirmed: bool | None) -> None:
                if confirmed:
                    self._do_remove(cascade=True)

            self.app.push_screen(
                ImpactConfirmScreen("database", label, impact),
                _after_impact,
            )
            return

        def _after_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._do_remove(cascade=False)

        self.app.push_screen(
            ConfirmScreen(
                "Remove database",
                f"Remove the RDS database '{label}'? This cannot be undone "
                "until you discard the draft.",
                confirm_label="Remove",
            ),
            _after_confirm,
        )

    def _do_remove(self, *, cascade: bool) -> None:
        # One document transaction so the database and every dependent reference
        # revert together as a unit until the draft is saved.
        with self.document.transaction():
            if cascade:
                remove_rds_with_references(self.document)
            else:
                self.document.reset("rds")
        self._enabled = False
        for field in self._editable_fields():
            field.touched = False
            field.clear_error()
            field.refresh_badge()
        self._apply_enabled_visibility()
        self._show_section_error(None)
        self.app.notify("Database removed from the draft.", severity="information")

    # -- events ------------------------------------------------------------

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        event.field.commit()
        self._sync_touched_errors()

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "rds-enable":
            event.stop()
            self._enable()
        elif button_id == "rds-remove":
            event.stop()
            self._handle_remove()
        elif button_id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())


__all__ = ["DatabaseSection"]
