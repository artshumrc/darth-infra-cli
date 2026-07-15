"""The Routing section: ALB host/path routing (ticket 08).

This section owns the ALB *routing* settings a project resolves once its load
balancer *identity* is chosen in Network: the cluster domain used for the default
host-header rule, the default target service that rule points at, an optional
preferred priority for that rule, and the list of additional path rules. Each
path rule names a unique identifier, a path pattern, a target service, and its
own optional preferred priority.

Listener priorities are only ever *preferred overrides* here. Automatic omits the
value so deployment assigns one; Override persists an explicit 1-50000 integer.
Nothing in this editor looks up or reserves a priority from AWS, and there is no
local priority allocator — deploy-time assignment stays authoritative and
preserves stack-owned priorities. Returning an existing explicit priority to
Automatic is a reset (key removal) and asks for confirmation first.

ALB mode and resource identity (shared versus dedicated, the shared ALB name,
listener/security-group overrides, and the dedicated certificate) belong to
Network. This section only *displays* that context and links back to Network
rather than duplicating those controls. CloudFront routing is owned by ticket 09.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Static

from ...config.models import _rule_param_suffix
from ..field_registry import registry_entry
from .collection import NestedCollectionEditor
from .widgets import (
    EditableField,
    OptionalIntegerField,
    ServiceSelectField,
    TextField,
    dom_slug,
)

_PATH_RULES = "alb.path_rules"

# Advanced (collapsible) scalar paths owned by this section, used for the
# configured-count and auto-expand computed from the document during compose.
_ADVANCED_PATHS = ("alb.default_listener_priority",)

_PRIORITY_HELP_CONSTRAINT = (
    "Automatic lets deployment allocate a priority; Override sets a preferred "
    "1-50000 value. Explicit priorities are preferences only — existing "
    "stack-owned priorities are preserved during deploy."
)


def _help(path: str) -> str:
    entry = registry_entry(path)
    return entry.help if entry else ""


def _example(path: str) -> str | None:
    entry = registry_entry(path)
    return entry.example if entry else None


class RoutingSection(VerticalScroll):
    """Editor for ALB host/path routing: domain, default target, and path rules."""

    class SaveContinueRequested(Message):
        """Posted when the section's Save & Continue action is pressed."""

    class NavigateToNetworkRequested(Message):
        """Posted when the operator asks to edit ALB identity in Network."""

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Routing", classes="section-title")
        yield Static("", id="section-error", classes="field-error")

        # ALB identity/mode context lives in Network; show it and link there.
        yield Static(
            self._mode_context_text(),
            id="routing-mode-context",
            classes="field-help",
        )
        yield Button(
            "Edit ALB identity in Network",
            id="routing-goto-network",
            compact=True,
        )

        yield TextField(
            field_path="alb.domain",
            document=self.document,
            label="Cluster domain",
            help=_help("alb.domain"),
            constraints="host-header for the default rule; required for any routing",
            example="app.example.com",
        )
        yield ServiceSelectField(
            field_path="alb.default_target_service",
            document=self.document,
            label="Default target service",
            help=_help("alb.default_target_service"),
            constraints="receives the default host-header rule; needs a container port",
            eligible=self._eligible_services(),
        )

        yield Collapsible(
            OptionalIntegerField(
                field_path="alb.default_listener_priority",
                document=self.document,
                label="Default rule priority",
                help=_help("alb.default_listener_priority"),
                constraints=_PRIORITY_HELP_CONSTRAINT,
            ),
            title=self._advanced_title(),
            id="advanced-routing",
            collapsed=not self._advanced_should_expand(),
        )

        yield self._path_rules_editor()

        yield Button("Save & Continue", id="save-continue", variant="primary")

    def _path_rules_editor(self) -> NestedCollectionEditor:
        def build(base: str) -> list[EditableField]:
            return [
                TextField(
                    field_path=f"{base}.name",
                    document=self.document,
                    label="Rule name",
                    help=_help("alb.path_rules[].name"),
                    constraints="unique; also unique after normalization",
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.path_pattern",
                    document=self.document,
                    label="Path pattern",
                    help=_help("alb.path_rules[].path_pattern"),
                    example=_example("alb.path_rules[].path_pattern"),
                    required=True,
                ),
                ServiceSelectField(
                    field_path=f"{base}.target_service",
                    document=self.document,
                    label="Target service",
                    help=_help("alb.path_rules[].target_service"),
                    constraints="needs a container port",
                    eligible=self._eligible_services(),
                    required=True,
                ),
                OptionalIntegerField(
                    field_path=f"{base}.priority",
                    document=self.document,
                    label="Preferred priority",
                    help=_help("alb.path_rules[].priority"),
                    constraints=_PRIORITY_HELP_CONSTRAINT,
                ),
            ]

        return NestedCollectionEditor(
            document=self.document,
            collection_path=_PATH_RULES,
            noun="path rule",
            title="Path rules",
            build_fields=build,
            record_label=lambda raw, i: str(raw.get("name") or "(unnamed rule)"),
            record_invalid=self._rule_invalid,
            new_record=lambda: {
                "name": "",
                "path_pattern": "",
                "target_service": "",
            },
            empty_message="No path rules configured.",
        )

    def on_mount(self) -> None:
        for field in self._scalar_fields():
            field.refresh_badge()
        self._show_section_error(None)

    # -- eligibility / context ---------------------------------------------

    def _eligible_services(self) -> list[str]:
        """Service names eligible as a routing target (those with a port).

        Mirrors the model rule that ALB targets must reference a service with a
        container port. Computed from raw records so it stays available even when
        the full draft does not yet parse.
        """
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
            if raw.get("port") is not None:
                name = str(raw.get("name") or "").strip()
                if name:
                    names.append(name)
        return names

    def _mode_context_text(self) -> str:
        mode = str(self._safe_value("alb.mode") or "shared")
        if mode == "dedicated":
            return "ALB identity: dedicated (managed in Network)."
        shared_name = str(self._safe_value("alb.shared_alb_name") or "").strip()
        if shared_name:
            return (
                f"ALB identity: shared, looking up '{shared_name}' "
                "(managed in Network)."
            )
        return "ALB identity: shared (managed in Network)."

    def _safe_value(self, path: str) -> Any:
        """Read an effective value, tolerating a temporarily invalid draft."""
        try:
            return self.document.value(path)
        except Exception:
            return self.document.raw_value(path)

    # -- field access ------------------------------------------------------

    def _scalar_fields(self) -> list[EditableField]:
        """The section's own scalar fields, excluding nested path-rule fields."""
        result: list[EditableField] = []
        for field in self.query(EditableField):
            node = field.parent
            nested = False
            while node is not None and node is not self:
                if isinstance(node, NestedCollectionEditor):
                    nested = True
                    break
                node = node.parent
            if not nested:
                result.append(field)
        return result

    def _field(self, path: str) -> EditableField | None:
        try:
            return self.query_one(f"#field-{dom_slug(path)}", EditableField)
        except Exception:
            return None

    def _path_rules_ed(self) -> NestedCollectionEditor | None:
        try:
            return self.query_one(
                f"#nested-{dom_slug(_PATH_RULES)}", NestedCollectionEditor
            )
        except Exception:
            return None

    # -- path-rule row validity -------------------------------------------

    def _default_priority(self) -> int | None:
        value = self.document.raw_value("alb.default_listener_priority")
        return value if isinstance(value, int) else None

    def _rule_invalid(
        self, raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
    ) -> bool:
        name = str(raw.get("name") or "").strip()
        if not name:
            return True
        siblings = [
            str(other.get("name") or "").strip()
            for i, other in enumerate(all_raw)
            if i != index
        ]
        if name in siblings:
            return True
        # Normalized parameter-key collision (the model rejects these too).
        suffix = _rule_param_suffix(name)
        if any(_rule_param_suffix(other) == suffix for other in siblings if other):
            return True

        if not str(raw.get("path_pattern") or "").strip():
            return True

        target = str(raw.get("target_service") or "").strip()
        if not target or target not in self._eligible_services():
            return True

        priority = raw.get("priority")
        if priority is not None:
            if not isinstance(priority, int) or not (1 <= priority <= 50000):
                return True
            others: set[int] = set()
            default = self._default_priority()
            if default is not None:
                others.add(default)
            for i, other in enumerate(all_raw):
                if i == index:
                    continue
                op = other.get("priority")
                if isinstance(op, int):
                    others.add(op)
            if priority in others:
                return True
        return False

    def _path_rules_has_error(self) -> bool:
        editor = self._path_rules_ed()
        return editor is not None and editor.has_error()

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
            panel = self.query_one("#advanced-routing", Collapsible)
        except Exception:
            return
        panel.title = self._advanced_title()
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_all(self) -> None:
        for field in self._scalar_fields():
            field.commit()
        editor = self._path_rules_ed()
        if editor is not None:
            editor.commit_all()

    def _field_errors(self) -> dict[str, str]:
        self._commit_all()
        errors: dict[str, str] = {}

        for field in self._scalar_fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        if self._path_rules_has_error():
            errors.setdefault(
                "__section__", "Fix the highlighted path rules before saving."
            )

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            if "alb.domain is required" in lowered:
                errors.setdefault("alb.domain", error)
            elif "default_target_service" in lowered:
                errors.setdefault("alb.default_target_service", error)
            elif "default_listener_priority" in lowered:
                errors.setdefault("alb.default_listener_priority", error)
            elif "path_rules" in lowered or "listener priority" in lowered:
                errors.setdefault("__section__", error)
            else:
                errors.setdefault("__section__", error)
        return errors

    def _sync_touched_errors(self) -> None:
        errors = self._field_errors()
        for field in self._scalar_fields():
            if field.touched:
                message = errors.get(field.field_path)
                if message:
                    field.show_error(message)
                else:
                    field.clear_error()
            field.refresh_badge()
        self._show_section_error(errors.get("__section__"))
        self._refresh_advanced()

    def validate_all(self) -> list[Any]:
        errors = self._field_errors()
        invalid: list[Any] = []
        for field in self._scalar_fields():
            message = errors.get(field.field_path)
            if message:
                field.touched = True
                field.show_error(message)
                invalid.append(field)
            elif field.touched:
                field.clear_error()
            field.refresh_badge()
        editor = self._path_rules_ed()
        if editor is not None and editor.has_error():
            invalid.append(editor)
        self._show_section_error(errors.get("__section__"))
        self._refresh_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._scalar_fields():
            field.mark_committed()
            field.refresh_badge()
        editor = self._path_rules_ed()
        if editor is not None:
            editor.refresh_markers()
        self._refresh_advanced()

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

    def on_nested_collection_editor_changed(
        self, event: NestedCollectionEditor.Changed
    ) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())
        elif button_id == "routing-goto-network":
            event.stop()
            self.post_message(self.NavigateToNetworkRequested())


__all__ = ["RoutingSection"]
