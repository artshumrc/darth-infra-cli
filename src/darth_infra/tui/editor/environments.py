"""The Environments section: environment overrides and preview policy (ticket 13).

Environments is the single editing location for environment-specific overrides,
environment tags, and preview-environment policy. It never edits the environment
*list* (that stays in Project, as ``project.environments``) nor the runtime-only
``active_preview`` metadata (which is not part of the persisted schema and has no
registry control by construction).

Two things live here:

* **Per-environment overrides.** A master list of the configured environments
  beside an editor for the selected one. Each editor shows the environment's
  effective values with an ``INHERITED`` or ``OVERRIDE`` badge and covers every
  persisted override the schema supports: the RDS instance-type override (only
  when a database is configured), the per-service EC2 instance-type overrides
  (keyed by an existing service so the map cannot name a service that does not
  exist), and the environment tags. ``Reset to inherited`` removes a persisted
  override key, restoring inheritance. Removing or renaming a service or the
  database cleans up its overrides through the shared reference-impact behavior
  in the owning sections; this section only edits them.

* **Preview-environment policy.** Every persisted ``preview_environments`` field
  — enabled, base environment, name pattern, domain template, hosted-zone name,
  the paired listener-priority bounds, and preview tags — grouped under a clearly
  optional panel that auto-opens when any preview field is already configured.
  Priority bounds remain editable because they reserve an allocation range for
  active previews; pairing, range, and ordering errors surface inline. Existing
  ordering, base-environment, tag interpolation, priority allocation, and preview
  deployment semantics are unchanged: this section only reads and writes the
  persisted fields the model already validates.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Static,
)

from ..field_registry import registry_entry
from .theme import BADGE_INHERITED, BADGE_OVERRIDE
from .widgets import (
    BooleanField,
    EditableField,
    IntegerField,
    KeyValueMapField,
    TextField,
    dom_slug,
)

# Preview fields grouped under the optional panel, in display order.
_PREVIEW_PATHS = (
    "preview_environments.enabled",
    "preview_environments.base_environment",
    "preview_environments.name_pattern",
    "preview_environments.domain_template",
    "preview_environments.hosted_zone_name",
    "preview_environments.listener_priority_start",
    "preview_environments.listener_priority_end",
    "preview_environments.tags",
)


def _help(path: str) -> str:
    entry = registry_entry(path)
    return entry.help if entry else ""


def _example(path: str) -> str | None:
    entry = registry_entry(path)
    return entry.example if entry else None


class InheritedOverrideField(TextField):
    """A per-environment scalar override with INHERITED/OVERRIDE presentation.

    An empty control inherits the base value; a non-empty control persists an
    explicit override. The badge reads ``OVERRIDE`` when the key is explicitly
    present and ``INHERITED`` otherwise, the effective inherited value is shown in
    the help line without being persisted, and ``Reset to inherited`` removes the
    persisted key to restore inheritance.
    """

    def __init__(self, *, inherited_display: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._inherited_display = inherited_display

    def _compose_control(self):
        yield from super()._compose_control()
        with Horizontal(classes="mode-row"):
            yield Button(
                "Reset to inherited",
                id=f"reset-{self.slug}",
                classes="mode-toggle",
                compact=True,
            )

    def _help_text(self) -> str:
        base = super()._help_text()
        inherited = f"Inherited: {self._inherited_display}"
        return f"{base}   ·   {inherited}" if base else inherited

    def _badge_text(self) -> str:
        try:
            explicit = self.document.is_explicit(self.field_path)
        except Exception:
            explicit = False
        return BADGE_OVERRIDE if explicit else BADGE_INHERITED

    def refresh_badge(self) -> None:
        badge = self.query_one(f"#badge-{self.slug}", Static)
        text = self._badge_text()
        badge.update(text)
        badge.set_class(text == BADGE_OVERRIDE, "badge-explicit")
        badge.set_class(text == BADGE_INHERITED, "badge-default")

    def reset_to_inherited(self) -> None:
        self.document.reset(self.field_path)
        self._input().value = ""
        self.mark_committed()
        self.refresh_badge()
        self._notify_changed()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == f"reset-{self.slug}":
            event.stop()
            self.reset_to_inherited()


class EnvironmentOverrideDetail(Vertical):
    """Editor for one environment's persisted overrides.

    A dumb container: its :class:`EditableField` children bubble their change and
    blur events up to :class:`EnvironmentsSection`, which owns validation and
    persistence. Fields are bound to concrete ``environments.<env>.*`` paths.
    """

    def __init__(
        self,
        document: Any,
        env: str,
        *,
        rds_configured: bool,
        rds_base_instance_type: str,
        service_names: list[str],
    ) -> None:
        super().__init__(id="env-detail", classes="detail-form")
        self.document = document
        self.env = env
        self._rds_configured = rds_configured
        self._rds_base_instance_type = rds_base_instance_type
        self._service_names = service_names

    def _path(self, field: str) -> str:
        return f"environments.{self.env}.{field}"

    def compose(self) -> ComposeResult:
        yield Static(
            f"Overrides for environment: {self.env}",
            classes="section-subtitle",
        )

        if self._rds_configured:
            yield InheritedOverrideField(
                field_path=self._path("instance_type_override"),
                document=self.document,
                label="RDS instance type override",
                help=_help("environments.*.instance_type_override"),
                constraints="normalized to include the required 'db.' prefix",
                example="db.r6g.large",
                inherited_display=self._rds_base_instance_type,
            )
        else:
            yield Static(
                "No database is configured, so there is no RDS instance type to "
                "override for this environment. Enable RDS in the Database "
                "section first.",
                id="env-no-rds",
                classes="field-help",
            )

        yield KeyValueMapField(
            field_path=self._path("ec2_instance_type_override"),
            document=self.document,
            label="Per-service EC2 instance type overrides",
            help=_help("environments.*.ec2_instance_type_override.*"),
            key_options=self._service_names,
            key_placeholder="service",
            value_placeholder="instance type (e.g. t3.large)",
        )
        if not self._service_names:
            yield Static(
                "No services yet. Add services in the Services section before "
                "overriding their EC2 instance types.",
                id="env-no-services",
                classes="field-help",
            )

        yield KeyValueMapField(
            field_path=self._path("tags"),
            document=self.document,
            label="Environment tags",
            help=_help("environments.*.tags.*"),
            example="huit_assetid = 12057",
        )

    def fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def focus_first(self) -> None:
        for field in self.fields():
            inputs = field.query(Input)
            if inputs:
                inputs.first().focus()
                return


class EnvironmentsSection(VerticalScroll):
    """The Environments section: per-environment overrides and preview policy."""

    class SaveContinueRequested(Message):
        """Posted when the section's Save & Continue action is pressed."""

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document
        self._selected_env: str | None = None
        self._detail: EnvironmentOverrideDetail | None = None

    # -- environment / resource facts --------------------------------------

    def _environments(self) -> list[str]:
        try:
            value = self.document.value("project.environments")
        except Exception:
            value = None
        if isinstance(value, (list, tuple)) and value:
            return [str(env) for env in value]
        return ["prod"]

    def _rds_configured(self) -> bool:
        try:
            return bool(self.document.is_explicit("rds"))
        except Exception:
            return False

    def _rds_base_instance_type(self) -> str:
        try:
            value = self.document.value("rds.instance_type")
        except Exception:
            value = None
        return str(value) if value else "db.t4g.micro"

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
        yield Static("Environments", classes="section-title")
        yield Static("", id="section-error", classes="field-error")

        yield Static(
            "Per-environment overrides. The environment list itself is edited in "
            "Project; project-wide tags stay in Project.",
            classes="field-help",
        )
        with Horizontal(id="md-body"):
            with Vertical(id="env-list", classes="md-list"):
                for env in self._environments():
                    yield Button(
                        env,
                        id=f"env-btn-{dom_slug(env)}",
                        classes="env-item",
                        compact=True,
                    )
            yield Container(id="env-detail-host", classes="md-detail")

        yield Collapsible(
            *self._preview_widgets(),
            title=self._preview_title(),
            id="preview-panel",
            collapsed=not self._preview_should_expand(),
        )

        yield Button("Save & Continue", id="save-continue", variant="primary")

    def _preview_widgets(self) -> list[Any]:
        return [
            Static(
                "Optional. Dynamic preview environments (for example per-PR "
                "deployments) do not appear in the environment list above. "
                "Runtime preview metadata is never edited here.",
                classes="field-help",
            ),
            BooleanField(
                field_path="preview_environments.enabled",
                document=self.document,
                label="Enable preview environments",
                help=_help("preview_environments.enabled"),
                default_display="false",
            ),
            TextField(
                field_path="preview_environments.base_environment",
                document=self.document,
                label="Base environment",
                help=_help("preview_environments.base_environment"),
                default_display="prod",
                constraints="must reference a configured environment",
            ),
            TextField(
                field_path="preview_environments.name_pattern",
                document=self.document,
                label="Name pattern",
                help=_help("preview_environments.name_pattern"),
                default_display="pr-{number}",
                constraints="must contain {number}",
                example=_example("preview_environments.name_pattern"),
            ),
            TextField(
                field_path="preview_environments.domain_template",
                document=self.document,
                label="Domain template",
                help=_help("preview_environments.domain_template"),
                constraints="must contain {number} when set",
                example="pr-{number}.example.com",
            ),
            TextField(
                field_path="preview_environments.hosted_zone_name",
                document=self.document,
                label="Hosted zone name",
                help=_help("preview_environments.hosted_zone_name"),
                example="example.com",
            ),
            IntegerField(
                field_path="preview_environments.listener_priority_start",
                document=self.document,
                label="Listener priority range start",
                help=_help("preview_environments.listener_priority_start"),
                constraints="1-50000; set together with the range end",
            ),
            IntegerField(
                field_path="preview_environments.listener_priority_end",
                document=self.document,
                label="Listener priority range end",
                help=_help("preview_environments.listener_priority_end"),
                constraints="1-50000; must be >= the range start",
            ),
            KeyValueMapField(
                field_path="preview_environments.tags",
                document=self.document,
                label="Preview tags",
                help=_help("preview_environments.tags.*"),
                example="ephemeral-cleanup-id = {project}-{env}",
            ),
        ]

    async def on_mount(self) -> None:
        self._refresh_env_list()
        environments = self._environments()
        if environments:
            await self._select_env(environments[0], focus_detail=False)
        for field in self._preview_fields():
            field.refresh_badge()
        self._show_section_error(None)

    # -- environment master list -------------------------------------------

    def _refresh_env_list(self) -> None:
        for env in self._environments():
            try:
                button = self.query_one(f"#env-btn-{dom_slug(env)}", Button)
            except Exception:
                continue
            marker = "◆" if self._env_has_override(env) else "·"
            button.label = f"{marker} {env}"
            button.set_class(env == self._selected_env, "env-active")

    def _env_has_override(self, env: str) -> bool:
        for field in ("instance_type_override", "tags", "ec2_instance_type_override"):
            try:
                value = self.document.value(f"environments.{env}.{field}")
            except Exception:
                value = None
            if isinstance(value, dict):
                if value:
                    return True
            elif value is not None:
                return True
        return False

    async def _select_env(self, env: str, *, focus_detail: bool = True) -> None:
        # Persist the currently open environment's edits before switching away.
        if self._detail is not None:
            for field in self._detail.fields():
                field.commit()
        self._selected_env = env
        host = self.query_one("#env-detail-host", Container)
        await host.remove_children()
        detail = EnvironmentOverrideDetail(
            self.document,
            env,
            rds_configured=self._rds_configured(),
            rds_base_instance_type=self._rds_base_instance_type(),
            service_names=self._service_names(),
        )
        self._detail = detail
        await host.mount(detail)
        for field in detail.fields():
            field.refresh_badge()
        self._refresh_env_list()
        if focus_detail:
            detail.focus_first()

    def _env_for_button(self, button_id: str) -> str | None:
        for env in self._environments():
            if button_id == f"env-btn-{dom_slug(env)}":
                return env
        return None

    # -- field access ------------------------------------------------------

    def _preview_fields(self) -> list[EditableField]:
        try:
            panel = self.query_one("#preview-panel", Collapsible)
        except Exception:
            return []
        return list(panel.query(EditableField))

    def _all_fields(self) -> list[EditableField]:
        fields = self._preview_fields()
        if self._detail is not None:
            fields = list(self._detail.fields()) + fields
        return fields

    def _field(self, path: str) -> EditableField | None:
        for field in self._all_fields():
            if field.field_path == path:
                return field
        return None

    # -- preview panel -----------------------------------------------------

    def _preview_configured_count(self) -> int:
        count = 0
        for path in _PREVIEW_PATHS:
            try:
                value = self.document.value(path)
            except Exception:
                value = None
            if isinstance(value, dict):
                if value:
                    count += 1
            else:
                try:
                    if self.document.is_explicit(path):
                        count += 1
                except Exception:
                    pass
        return count

    def _preview_has_error(self) -> bool:
        return any(field.error for field in self._preview_fields())

    def _preview_title(self) -> str:
        return f"Preview environments — optional ({self._preview_configured_count()} configured)"

    def _preview_should_expand(self) -> bool:
        # An active preview configuration forces the panel open.
        return self._preview_configured_count() > 0 or self._preview_has_error()

    def _refresh_preview_panel(self) -> None:
        try:
            panel = self.query_one("#preview-panel", Collapsible)
        except Exception:
            return
        panel.title = self._preview_title()
        if self._preview_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_all(self) -> None:
        for field in self._all_fields():
            field.commit()

    def _field_errors(self) -> dict[str, str]:
        self._commit_all()
        errors: dict[str, str] = {}

        for field in self._all_fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            if "base_environment" in lowered:
                errors.setdefault(
                    "preview_environments.base_environment", error
                )
            elif "name_pattern" in lowered:
                errors.setdefault("preview_environments.name_pattern", error)
            elif "domain_template" in lowered:
                errors.setdefault("preview_environments.domain_template", error)
            elif (
                "listener_priority_start" in lowered
                and "<=" in error
            ):
                errors.setdefault(
                    "preview_environments.listener_priority_start", error
                )
            elif "listener_priority_start" in lowered and "together" in lowered:
                errors.setdefault(
                    "preview_environments.listener_priority_start", error
                )
            elif "listener_priority_start" in lowered:
                errors.setdefault(
                    "preview_environments.listener_priority_start", error
                )
            elif "listener_priority_end" in lowered:
                errors.setdefault(
                    "preview_environments.listener_priority_end", error
                )
            elif "instance_type_override" in lowered and self._detail is not None:
                path = f"environments.{self._detail.env}.instance_type_override"
                if self._field(path) is not None:
                    errors.setdefault(path, error)
                else:
                    errors.setdefault("__section__", error)
            else:
                errors.setdefault("__section__", error)
        return errors

    def _sync_touched_errors(self) -> None:
        errors = self._field_errors()
        for field in self._all_fields():
            if field.touched:
                message = errors.get(field.field_path)
                if message:
                    field.show_error(message)
                else:
                    field.clear_error()
            field.refresh_badge()
        self._show_section_error(errors.get("__section__"))
        self._refresh_preview_panel()
        self._refresh_env_list()

    def validate_all(self) -> list[EditableField]:
        errors = self._field_errors()
        invalid: list[EditableField] = []
        for field in self._all_fields():
            message = errors.get(field.field_path)
            if message:
                field.touched = True
                field.show_error(message)
                invalid.append(field)
            elif field.touched:
                field.clear_error()
            field.refresh_badge()
        self._show_section_error(errors.get("__section__"))
        self._refresh_preview_panel()
        self._refresh_env_list()
        return invalid

    def after_save(self) -> None:
        for field in self._all_fields():
            field.mark_committed()
            field.refresh_badge()
        self._refresh_preview_panel()
        self._refresh_env_list()

    def _show_section_error(self, message: str | None) -> None:
        banner = self.query_one("#section-error", Static)
        if message:
            banner.update(f"✗ {message}")
            banner.display = True
        else:
            banner.update("")
            banner.display = False

    # -- events ------------------------------------------------------------

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        event.field.commit()
        self._sync_touched_errors()

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())
            return
        env = self._env_for_button(button_id)
        if env is not None:
            event.stop()
            if env != self._selected_env:
                await self._select_env(env)


__all__ = [
    "EnvironmentsSection",
    "EnvironmentOverrideDetail",
    "InheritedOverrideField",
]
