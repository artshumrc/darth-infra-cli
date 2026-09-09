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
rather than duplicating those controls.

CloudFront routing lives here too. Its settings stay hidden behind an enable
control, but any existing configured value forces the panel open so navigation
never conceals — or discards — it. The certificate ARN is a searchable AWS
reference with manual entry; service connections and cached behaviors are
master-detail collections. A cached behavior's query-string/cookie allowlists
appear only in allowlist mode, and switching a mode away from allowlist confirms
before removing the values it hides. Nothing here renders, deploys, or discovers
distributions; deploy-time resolution and the model's cross-field rules stay
authoritative.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Input, Select, Static

from ...config.models import CloudFrontCachedBehavior, _rule_param_suffix
from ..field_registry import registry_entry
from .aws_discovery import AwsDiscovery, DiscoveryKind, OfflineAwsDiscovery
from .collection import ConfirmScreen, NestedCollectionEditor
from .widgets import (
    AwsReferenceField,
    BooleanField,
    EditableField,
    IntegerField,
    OptionalIntegerField,
    SelectField,
    ServiceSelectField,
    StringListField,
    TextField,
    dom_slug,
)

_PATH_RULES = "alb.path_rules"
_CF_CONNECTIONS = "cloudfront.connections"
_CF_BEHAVIORS = "cloudfront.cached_behaviors"

# Advanced (collapsible) scalar paths owned by this section, used for the
# configured-count and auto-expand computed from the document during compose.
_ADVANCED_PATHS = ("alb.default_listener_priority",)

# CloudFront advanced (collapsible) scalar paths.
_CF_ADVANCED_PATHS = (
    "cloudfront.origin_https_only",
    "cloudfront.custom_domain",
    "cloudfront.certificate_arn",
    "cloudfront.price_class",
    "cloudfront.comment",
)

_PRIORITY_HELP_CONSTRAINT = (
    "Automatic lets deployment allocate a priority; Override sets a preferred "
    "1-50000 value. Explicit priorities are preferences only — existing "
    "stack-owned priorities are preserved during deploy."
)

_PRICE_CLASS_OPTIONS = [
    ("PriceClass_100 (US, Canada, Europe)", "PriceClass_100"),
    ("PriceClass_200 (adds Asia, Middle East, Africa)", "PriceClass_200"),
    ("PriceClass_All (all edge locations)", "PriceClass_All"),
]
_QUERY_STRING_OPTIONS = [
    ("Forward all", "all"),
    ("Forward none", "none"),
    ("Allowlist", "allowlist"),
]
_COOKIE_OPTIONS = [
    ("Forward none", "none"),
    ("Forward all", "all"),
    ("Allowlist", "allowlist"),
]

# Effective defaults for a cached behavior, used to render numeric/boolean/select
# controls correctly even when the draft is temporarily unparseable (a sibling
# record is mid-edit) so the editor shows the same default the model would apply.
_BEHAVIOR_DEFAULTS = CloudFrontCachedBehavior(name="", path_pattern="")


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

    def __init__(
        self, document: Any, discovery: AwsDiscovery | None = None
    ) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document
        # AWS discovery is injected and optional; the CloudFront certificate
        # reference offers discovered ACM certificates but manual entry and
        # locally valid saves never depend on it.
        self._discovery = discovery or OfflineAwsDiscovery()

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

        # -- CloudFront ----------------------------------------------------
        yield Static("CloudFront", classes="section-title")
        yield BooleanField(
            field_path="cloudfront.enabled",
            document=self.document,
            label="Enable CloudFront",
            help=_help("cloudfront.enabled"),
            constraints="needs a cluster domain and at least one cached behavior",
        )
        with Vertical(id="cloudfront-panel", classes="cloudfront-panel"):
            yield Collapsible(
                *self._cloudfront_advanced_widgets(),
                title=self._cf_advanced_title(),
                id="advanced-cloudfront",
                collapsed=not self._cf_advanced_should_expand(),
            )
            yield self._connections_editor()
            yield self._behaviors_editor()

        yield Button("Save & Continue", id="save-continue", variant="primary")

    # -- CloudFront composition -------------------------------------------

    def _cloudfront_advanced_widgets(self) -> list[EditableField]:
        return [
            BooleanField(
                field_path="cloudfront.origin_https_only",
                document=self.document,
                label="Connect to ALB origin over HTTPS only",
                help=_help("cloudfront.origin_https_only"),
                constraints="dedicated mode requires an ALB certificate",
                fallback=False,
            ),
            TextField(
                field_path="cloudfront.custom_domain",
                document=self.document,
                label="Custom domain",
                help=_help("cloudfront.custom_domain"),
                constraints="hostname only; must be paired with a certificate ARN",
                example="cdn.example.com",
            ),
            AwsReferenceField(
                field_path="cloudfront.certificate_arn",
                document=self.document,
                label="Certificate ARN",
                help=_help("cloudfront.certificate_arn"),
                constraints="ACM certificate in us-east-1; paired with the custom domain",
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.CERTIFICATE,
            ),
            SelectField(
                field_path="cloudfront.price_class",
                document=self.document,
                label="Price class",
                help=_help("cloudfront.price_class"),
                default_display="PriceClass_100",
                options=_PRICE_CLASS_OPTIONS,
                fallback="PriceClass_100",
            ),
            TextField(
                field_path="cloudfront.comment",
                document=self.document,
                label="Comment",
                help=_help("cloudfront.comment"),
            ),
        ]

    def _connections_editor(self) -> NestedCollectionEditor:
        def build(base: str) -> list[EditableField]:
            return [
                ServiceSelectField(
                    field_path=f"{base}.service",
                    document=self.document,
                    label="Service",
                    help=_help("cloudfront.connections[].service"),
                    constraints="receives the CloudFront URL env var",
                    eligible=self._all_service_names(),
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.env_key",
                    document=self.document,
                    label="Env var key",
                    help=_help("cloudfront.connections[].env_key"),
                    example=_example("cloudfront.connections[].env_key"),
                    required=True,
                ),
            ]

        return NestedCollectionEditor(
            document=self.document,
            collection_path=_CF_CONNECTIONS,
            noun="connection",
            title="Service connections",
            build_fields=build,
            record_label=self._connection_label,
            record_invalid=self._connection_invalid,
            new_record=lambda: {"service": "", "env_key": ""},
            empty_message="No CloudFront service connections configured.",
        )

    def _behaviors_editor(self) -> NestedCollectionEditor:
        return NestedCollectionEditor(
            document=self.document,
            collection_path=_CF_BEHAVIORS,
            noun="cached behavior",
            title="Cached behaviors",
            build_fields=lambda base: [],
            build_detail=lambda base, index: CachedBehaviorDetail(
                self.document, base, index
            ),
            record_label=lambda raw, i: str(raw.get("name") or "(unnamed behavior)"),
            record_invalid=_behavior_invalid,
            new_record=lambda: {"name": "", "path_pattern": ""},
            empty_message="No cached behaviors configured.",
        )

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
        self._apply_cloudfront_visibility()
        self._show_section_error(None)

    # -- eligibility / context ---------------------------------------------

    def _all_service_names(self) -> list[str]:
        """Every configured service name (CloudFront connections accept any).

        A CloudFront connection only needs the service to exist, so — unlike ALB
        targets — a port-less worker is eligible. Computed from raw records so it
        remains available while the full draft does not yet parse.
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
            name = str(raw.get("name") or "").strip()
            if name:
                names.append(name)
        return names

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
        return self._nested_ed(_PATH_RULES)

    def _nested_ed(self, collection_path: str) -> NestedCollectionEditor | None:
        try:
            return self.query_one(
                f"#nested-{dom_slug(collection_path)}", NestedCollectionEditor
            )
        except Exception:
            return None

    def _nested_editors(self) -> list[NestedCollectionEditor]:
        return list(self.query(NestedCollectionEditor))

    # -- CloudFront connection row validity -------------------------------

    def _connection_label(self, raw: dict[str, Any], index: int) -> str:
        env_key = str(raw.get("env_key") or "").strip()
        service = str(raw.get("service") or "").strip()
        if env_key and service:
            return f"{env_key} -> {service}"
        return env_key or service or "(new connection)"

    def _connection_invalid(
        self, raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
    ) -> bool:
        service = str(raw.get("service") or "").strip()
        if not service or service not in self._all_service_names():
            return True
        env_key = str(raw.get("env_key") or "").strip()
        if not env_key:
            return True
        pair = (service, env_key)
        for i, other in enumerate(all_raw):
            if i == index:
                continue
            other_pair = (
                str(other.get("service") or "").strip(),
                str(other.get("env_key") or "").strip(),
            )
            if other_pair == pair:
                return True
        return False

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

    # -- CloudFront panel visibility + advanced ---------------------------

    def _cf_enabled_current(self) -> bool:
        field = self._field("cloudfront.enabled")
        if field is not None:
            return bool(field.current_value())
        return bool(self._safe_value("cloudfront.enabled"))

    def _cloudfront_configured(self) -> bool:
        """Whether any CloudFront value is present (forces the panel open).

        Existing configuration must never be concealed — or discarded — merely by
        the enable toggle or by navigation, so a populated panel stays visible
        even while ``enabled`` is unchecked (which is itself an error the operator
        then sees and fixes).
        """
        for path in _CF_ADVANCED_PATHS:
            try:
                if self.document.is_explicit(path):
                    return True
            except Exception:
                pass
        for collection in (_CF_CONNECTIONS, _CF_BEHAVIORS):
            try:
                if self.document.record_count(collection) > 0:
                    return True
            except Exception:
                pass
        return False

    def _apply_cloudfront_visibility(self) -> None:
        try:
            panel = self.query_one("#cloudfront-panel", Vertical)
        except Exception:
            return
        panel.display = self._cf_enabled_current() or self._cloudfront_configured()

    def _cf_advanced_configured_count(self) -> int:
        count = 0
        for path in _CF_ADVANCED_PATHS:
            try:
                if self.document.is_explicit(path):
                    count += 1
            except Exception:
                pass
        return count

    def _cf_advanced_has_error(self) -> bool:
        return any(
            (f := self._field(path)) is not None and f.error
            for path in _CF_ADVANCED_PATHS
        )

    def _cf_advanced_title(self) -> str:
        return f"Advanced ({self._cf_advanced_configured_count()} configured)"

    def _cf_advanced_should_expand(self) -> bool:
        return self._cf_advanced_configured_count() > 0 or self._cf_advanced_has_error()

    def _refresh_cf_advanced(self) -> None:
        try:
            panel = self.query_one("#advanced-cloudfront", Collapsible)
        except Exception:
            return
        panel.title = self._cf_advanced_title()
        if self._cf_advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_all(self) -> None:
        for field in self._scalar_fields():
            field.commit()
        for editor in self._nested_editors():
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
        connections = self._nested_ed(_CF_CONNECTIONS)
        if connections is not None and connections.has_error():
            errors.setdefault(
                "__section__",
                "Fix the highlighted CloudFront connections before saving.",
            )
        behaviors = self._nested_ed(_CF_BEHAVIORS)
        if behaviors is not None and behaviors.has_error():
            errors.setdefault(
                "__section__",
                "Fix the highlighted cached behaviors before saving.",
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
            # -- CloudFront cross-field errors ----------------------------
            elif "cloudfront.enabled requires alb.domain" in lowered:
                errors.setdefault("alb.domain", error)
            elif "origin_https_only" in lowered:
                errors.setdefault("cloudfront.origin_https_only", error)
            elif "cached_behaviors" in lowered:
                errors.setdefault("__section__", error)
            elif "custom_domain" in lowered:
                errors.setdefault("cloudfront.custom_domain", error)
            elif "price_class" in lowered:
                errors.setdefault("cloudfront.price_class", error)
            elif "require cloudfront.enabled=true" in lowered:
                errors.setdefault("cloudfront.enabled", error)
            elif "cloudfront.connections" in lowered:
                errors.setdefault("__section__", error)
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
        self._refresh_cf_advanced()

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
        for editor in self._nested_editors():
            if editor.has_error():
                invalid.append(editor)
        self._show_section_error(errors.get("__section__"))
        self._refresh_advanced()
        self._refresh_cf_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._scalar_fields():
            field.mark_committed()
            field.refresh_badge()
        for editor in self._nested_editors():
            editor.refresh_markers()
        self._refresh_advanced()
        self._refresh_cf_advanced()

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
        self._apply_cloudfront_visibility()
        self._sync_touched_errors()

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_nested_collection_editor_changed(
        self, event: NestedCollectionEditor.Changed
    ) -> None:
        event.stop()
        self._apply_cloudfront_visibility()
        self._sync_touched_errors()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())
        elif button_id == "routing-goto-network":
            event.stop()
            self.post_message(self.NavigateToNetworkRequested())


def _behavior_invalid(
    raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
) -> bool:
    """Whether a cached-behavior record is invalid, mirroring the model rules.

    Computed from raw records (with the model's effective defaults filled in for
    omitted keys) so the list marker stays correct while the full draft — for
    example a sibling behavior mid-edit — does not yet parse.
    """
    name = str(raw.get("name") or "").strip()
    if not name:
        return True
    path = str(raw.get("path_pattern") or "").strip()
    if not path:
        return True
    for i, other in enumerate(all_raw):
        if i == index:
            continue
        if str(other.get("name") or "").strip() == name:
            return True
        if str(other.get("path_pattern") or "").strip() == path:
            return True

    min_ttl = raw.get("min_ttl_seconds", _BEHAVIOR_DEFAULTS.min_ttl_seconds)
    default_ttl = raw.get("default_ttl_seconds", _BEHAVIOR_DEFAULTS.default_ttl_seconds)
    max_ttl = raw.get("max_ttl_seconds", _BEHAVIOR_DEFAULTS.max_ttl_seconds)
    for value in (min_ttl, default_ttl, max_ttl):
        if not isinstance(value, int) or isinstance(value, bool):
            return True
    if min_ttl < 0 or default_ttl < min_ttl or max_ttl < default_ttl:
        return True

    query_mode = str(raw.get("query_strings", "all"))
    query_allow = raw.get("query_string_allowlist") or []
    if query_mode == "allowlist" and not query_allow:
        return True
    if query_mode != "allowlist" and query_allow:
        return True

    cookie_mode = str(raw.get("cookies", "none"))
    cookie_allow = raw.get("cookie_allowlist") or []
    if cookie_mode == "allowlist" and not cookie_allow:
        return True
    if cookie_mode != "allowlist" and cookie_allow:
        return True

    return False


class CachedBehaviorDetail(Vertical):
    """Editor for a single CloudFront cached behavior.

    Mounted by the cached-behaviors :class:`NestedCollectionEditor` as a record's
    custom detail. It owns the one piece of per-record conditional presentation
    the generic collection cannot: the query-string and cookie *allowlists* are
    shown only in allowlist mode, and switching a mode away from allowlist first
    confirms before removing the values it would hide — so hidden existing values
    survive until the operator explicitly discards them. Field-change events are
    observed (not consumed) so the collection still commits and re-marks the row.
    """

    def __init__(self, document: Any, base: str, index: int) -> None:
        super().__init__(id=f"cf-behavior-{index}", classes="nested-form")
        self.document = document
        self.base = base

    def _p(self, field: str) -> str:
        return f"{self.base}.{field}"

    def compose(self) -> ComposeResult:
        d = _BEHAVIOR_DEFAULTS
        yield TextField(
            field_path=self._p("name"),
            document=self.document,
            label="Behavior name",
            help=_help("cloudfront.cached_behaviors[].name"),
            constraints="unique across behaviors",
            required=True,
        )
        yield TextField(
            field_path=self._p("path_pattern"),
            document=self.document,
            label="Path pattern",
            help=_help("cloudfront.cached_behaviors[].path_pattern"),
            example=_example("cloudfront.cached_behaviors[].path_pattern"),
            constraints="unique across behaviors",
            required=True,
        )
        yield BooleanField(
            field_path=self._p("compress"),
            document=self.document,
            label="Compress objects automatically",
            help=_help("cloudfront.cached_behaviors[].compress"),
            default_display="true",
            fallback=d.compress,
        )
        yield BooleanField(
            field_path=self._p("cache_by_origin_headers"),
            document=self.document,
            label="Honor origin cache headers",
            help=_help("cloudfront.cached_behaviors[].cache_by_origin_headers"),
            default_display="true",
            fallback=d.cache_by_origin_headers,
        )
        yield IntegerField(
            field_path=self._p("min_ttl_seconds"),
            document=self.document,
            label="Minimum TTL (s)",
            help=_help("cloudfront.cached_behaviors[].min_ttl_seconds"),
            constraints="0 or more; must be <= default TTL",
            default_display="0",
            fallback=d.min_ttl_seconds,
        )
        yield IntegerField(
            field_path=self._p("default_ttl_seconds"),
            document=self.document,
            label="Default TTL (s)",
            help=_help("cloudfront.cached_behaviors[].default_ttl_seconds"),
            constraints="between minimum and maximum TTL",
            default_display="3600",
            fallback=d.default_ttl_seconds,
        )
        yield IntegerField(
            field_path=self._p("max_ttl_seconds"),
            document=self.document,
            label="Maximum TTL (s)",
            help=_help("cloudfront.cached_behaviors[].max_ttl_seconds"),
            constraints="must be >= default TTL",
            default_display="31536000",
            fallback=d.max_ttl_seconds,
        )
        yield SelectField(
            field_path=self._p("query_strings"),
            document=self.document,
            label="Query strings",
            help=_help("cloudfront.cached_behaviors[].query_strings"),
            default_display="all",
            options=_QUERY_STRING_OPTIONS,
            fallback=d.query_strings.value,
        )
        yield StringListField(
            field_path=self._p("query_string_allowlist"),
            document=self.document,
            label="Query string allowlist",
            help=_help("cloudfront.cached_behaviors[].query_string_allowlist"),
            constraints="required in allowlist mode",
        )
        yield SelectField(
            field_path=self._p("cookies"),
            document=self.document,
            label="Cookies",
            help=_help("cloudfront.cached_behaviors[].cookies"),
            default_display="none",
            options=_COOKIE_OPTIONS,
            fallback=d.cookies.value,
        )
        yield StringListField(
            field_path=self._p("cookie_allowlist"),
            document=self.document,
            label="Cookie allowlist",
            help=_help("cloudfront.cached_behaviors[].cookie_allowlist"),
            constraints="required in allowlist mode",
        )
        yield StringListField(
            field_path=self._p("origin_request_headers"),
            document=self.document,
            label="Origin request headers",
            help=_help("cloudfront.cached_behaviors[].origin_request_headers"),
            example=_example("cloudfront.cached_behaviors[].origin_request_headers"),
        )
        yield BooleanField(
            field_path=self._p("forward_authorization_header"),
            document=self.document,
            label="Forward Authorization header",
            help=_help("cloudfront.cached_behaviors[].forward_authorization_header"),
            default_display="false",
            fallback=d.forward_authorization_header,
        )

    def on_mount(self) -> None:
        self._apply_allowlist_visibility("query_strings", "query_string_allowlist")
        self._apply_allowlist_visibility("cookies", "cookie_allowlist")

    def _field(self, field: str) -> EditableField:
        return self.query_one(f"#field-{dom_slug(self._p(field))}", EditableField)

    def _apply_allowlist_visibility(self, mode_field: str, allow_field: str) -> None:
        mode = self._field(mode_field).current_value()
        self._field(allow_field).display = mode == "allowlist"

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        # Observe, but do not stop: the owning NestedCollectionEditor still
        # commits the field and re-marks the row after this handler runs.
        path = event.field.field_path
        if path.endswith(".query_strings"):
            self._handle_mode_change(
                "query_strings", "query_string_allowlist", "query string"
            )
        elif path.endswith(".cookies"):
            self._handle_mode_change("cookies", "cookie_allowlist", "cookie")

    def _handle_mode_change(
        self, mode_field: str, allow_field: str, noun: str
    ) -> None:
        select = self._field(mode_field)
        allow = self._field(allow_field)
        mode = select.current_value()
        if mode == "allowlist":
            allow.display = True
            return
        if allow.current_value():
            def after(confirmed: bool | None) -> None:
                if confirmed:
                    self._clear_allowlist(allow)
                else:
                    # Keep the values: return the mode to allowlist. The document
                    # is set directly because the widget reverts to its loaded
                    # baseline, whose commit would otherwise be a no-op and leave
                    # the already-committed non-allowlist mode in place.
                    self.document.set(select.field_path, "allowlist")
                    select.query_one(f"#input-{select.slug}", Select).value = (
                        "allowlist"
                    )
                    allow.display = True

            self.app.push_screen(
                ConfirmScreen(
                    f"Remove {noun} allowlist?",
                    f"Switching “{select.label}” away from allowlist removes the "
                    f"configured {noun} allowlist. Continue?",
                    confirm_label="Remove allowlist",
                ),
                after,
            )
        else:
            allow.display = False

    def _clear_allowlist(self, allow: EditableField) -> None:
        allow.query_one(f"#input-{allow.slug}", Input).value = ""
        self.document.reset(allow.field_path)
        # Adopt the cleared value as the baseline so a later commit_all does not
        # rewrite an empty list back into the document.
        allow.mark_committed()
        allow.display = False


__all__ = ["RoutingSection", "CachedBehaviorDetail"]
