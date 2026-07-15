"""The Network section: VPC/subnet placement and ALB identity.

This section owns the network-topology settings a project must resolve before it
can deploy: which VPC to deploy into, which private/public subnets to place tasks
and a dedicated ALB in, and — for the load balancer's *identity* — whether the
project shares an existing ALB or provisions a dedicated one, plus the shared
listener/security-group overrides and the dedicated certificate. ALB *routing*
(host/path rules, target services, listener priorities) belongs to the Routing
section and to deploy-time resolution; nothing here looks up or allocates a
listener priority.

Every value is editable offline. AWS discovery and verification are optional and
sit behind the injected :class:`~darth_infra.tui.editor.aws_discovery.AwsDiscovery`
adapter, so selecting a discovered resource is a convenience, never a
requirement, and never silently replaces a value the operator typed.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Static

from ..field_registry import registry_entry
from .aws_discovery import AwsDiscovery, DiscoveryKind, OfflineAwsDiscovery
from .widgets import (
    AwsBackedField,
    AwsReferenceField,
    AwsSubnetListField,
    EditableField,
    SelectField,
    dom_slug,
)

# ALB-identity fields relevant only in shared mode.
_SHARED_ONLY = (
    "alb.shared_alb_name",
    "alb.shared_listener_arn",
    "alb.shared_alb_security_group_id",
)
# ALB-identity fields relevant only in dedicated mode.
_DEDICATED_ONLY = ("alb.certificate_arn",)

# Advanced (collapsible) paths owned by this section, for configured-count and
# auto-expand computed from the document during compose.
_ADVANCED_PATHS = (
    "project.vpc_id",
    "project.private_subnet_ids",
    "project.public_subnet_ids",
    "alb.shared_listener_arn",
    "alb.shared_alb_security_group_id",
    "alb.certificate_arn",
)


def _help(path: str) -> str:
    entry = registry_entry(path)
    return entry.help if entry else ""


def _example(path: str) -> str | None:
    entry = registry_entry(path)
    return entry.example if entry else None


class NetworkSection(VerticalScroll):
    """Editor for VPC/subnet placement and shared-versus-dedicated ALB identity."""

    class SaveContinueRequested(Message):
        """Posted when the section's Save & Continue action is pressed."""

    def __init__(
        self, document: Any, discovery: AwsDiscovery | None = None
    ) -> None:
        super().__init__(id="section-content", classes="section-content")
        self.document = document
        self._discovery = discovery or OfflineAwsDiscovery()
        # Parent context captured from discovered selections, used to scope
        # dependent lookups (VPC -> subnets, ALB -> listener/security group).
        self._selected_vpc_id: str | None = None
        self._selected_alb_arn: str | None = None

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Network", classes="section-title")
        yield Static("", id="section-error", classes="field-error")

        # -- VPC (lookup + override) --------------------------------------
        yield AwsReferenceField(
            field_path="project.vpc_name",
            document=self.document,
            label="VPC name",
            help=_help("project.vpc_name"),
            default_display="artshumrc-prod-standard",
            constraints="Name tag of the VPC; filters subnet discovery",
            example=_example("project.vpc_name"),
            discovery=self._discovery,
            discovery_kind=DiscoveryKind.VPC_NAME,
            verifiable=True,
            context_provider=self.discovery_context,
        )

        # -- ALB identity: mode + shared selector -------------------------
        yield SelectField(
            field_path="alb.mode",
            document=self.document,
            label="ALB mode",
            help=_help("alb.mode"),
            default_display="shared",
            options=[
                ("Shared (look up an existing ALB)", "shared"),
                ("Dedicated (provision a new ALB)", "dedicated"),
            ],
        )
        yield AwsReferenceField(
            field_path="alb.shared_alb_name",
            document=self.document,
            label="Shared ALB name",
            help=_help("alb.shared_alb_name"),
            constraints="the common shared-mode selector",
            discovery=self._discovery,
            discovery_kind=DiscoveryKind.LOAD_BALANCER,
            verifiable=True,
            context_provider=self.discovery_context,
        )

        # -- Advanced overrides -------------------------------------------
        yield Collapsible(
            *self._advanced_widgets(),
            title=self._advanced_title(),
            id="advanced-network",
            collapsed=not self._advanced_should_expand(),
        )

        yield Button("Save & Continue", id="save-continue", variant="primary")

    def _advanced_widgets(self) -> list[EditableField]:
        return [
            AwsReferenceField(
                field_path="project.vpc_id",
                document=self.document,
                label="VPC ID override",
                help=_help("project.vpc_id"),
                constraints="Automatic uses the VPC name lookup",
                example=_example("project.vpc_id"),
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.VPC_ID,
                verifiable=True,
                optional=True,
                context_provider=self.discovery_context,
            ),
            AwsSubnetListField(
                field_path="project.private_subnet_ids",
                document=self.document,
                label="Private subnet IDs",
                help=_help("project.private_subnet_ids"),
                constraints=(
                    "Automatic discovers them at deploy; override to control "
                    "placement and stay within the ECS 16-subnet limit"
                ),
                example=_example("project.private_subnet_ids"),
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.PRIVATE_SUBNETS,
                optional=True,
                context_provider=self.discovery_context,
            ),
            AwsSubnetListField(
                field_path="project.public_subnet_ids",
                document=self.document,
                label="Public subnet IDs",
                help=_help("project.public_subnet_ids"),
                constraints=(
                    "used only for a dedicated ALB; Automatic discovers them "
                    "at deploy"
                ),
                example=_example("project.public_subnet_ids"),
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.PUBLIC_SUBNETS,
                optional=True,
                context_provider=self.discovery_context,
            ),
            AwsReferenceField(
                field_path="alb.shared_listener_arn",
                document=self.document,
                label="Shared listener ARN override",
                help=_help("alb.shared_listener_arn"),
                constraints="advanced shared-mode override; Automatic by default",
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.LISTENER,
                optional=True,
                context_provider=self.discovery_context,
            ),
            AwsReferenceField(
                field_path="alb.shared_alb_security_group_id",
                document=self.document,
                label="Shared ALB security group ID override",
                help=_help("alb.shared_alb_security_group_id"),
                constraints="advanced shared-mode override; Automatic by default",
                discovery=self._discovery,
                discovery_kind=DiscoveryKind.SECURITY_GROUP,
                optional=True,
                context_provider=self.discovery_context,
            ),
            AwsReferenceField(
                field_path="alb.certificate_arn",
                document=self.document,
                label="Dedicated certificate ARN",
                help=_help("alb.certificate_arn"),
                constraints="ACM certificate ARN; used in dedicated mode",
                optional=True,
                context_provider=self.discovery_context,
            ),
        ]

    def on_mount(self) -> None:
        for field in self._editable_fields():
            field.refresh_badge()
        self._apply_mode_visibility()
        self._show_section_error(None)

    # -- field access ------------------------------------------------------

    def _editable_fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def _visible_fields(self) -> list[EditableField]:
        return [f for f in self._editable_fields() if f.display]

    def _field(self, path: str) -> EditableField | None:
        try:
            return self.query_one(f"#field-{dom_slug(path)}", EditableField)
        except Exception:
            return None

    # -- discovery context -------------------------------------------------

    def discovery_context(self, kind: DiscoveryKind | None) -> dict[str, Any]:
        """Return the parent identifiers a dependent lookup needs.

        VPC choices (explicit id, else the name, else a discovered id) scope
        subnet discovery; the shared-ALB choice (a discovered ARN, else the
        name) scopes listener and security-group discovery.
        """
        vpc_id_field = self._field("project.vpc_id")
        vpc_name_field = self._field("project.vpc_name")
        explicit_vpc_id = (
            str(vpc_id_field.current_value()) if vpc_id_field else ""
        ).strip()
        vpc_name = (
            str(vpc_name_field.current_value()) if vpc_name_field else ""
        ).strip()

        alb_name_field = self._field("alb.shared_alb_name")
        alb_name = (
            str(alb_name_field.current_value()) if alb_name_field else ""
        ).strip()

        return {
            "vpc_id": explicit_vpc_id or self._selected_vpc_id or None,
            "vpc_name": vpc_name or None,
            "load_balancer_arn": self._selected_alb_arn or None,
            "load_balancer_name": alb_name or None,
        }

    def on_aws_backed_field_record_selected(
        self, event: AwsBackedField.RecordSelected
    ) -> None:
        event.stop()
        path = event.field.field_path
        context = event.record.context
        if path in ("project.vpc_name", "project.vpc_id"):
            self._selected_vpc_id = (
                context.get("vpc_id") or event.record.value or None
            )
        elif path == "alb.shared_alb_name":
            self._selected_alb_arn = context.get("arn") or None

    # -- conditional presentation -----------------------------------------

    def _mode(self) -> str:
        field = self._field("alb.mode")
        value = field.current_value() if field else None
        return str(value) if value else "shared"

    def _apply_mode_visibility(self) -> None:
        shared = self._mode() == "shared"
        for path in _SHARED_ONLY:
            field = self._field(path)
            if field is not None:
                field.display = shared
        for path in _DEDICATED_ONLY:
            field = self._field(path)
            if field is not None:
                field.display = not shared

    # -- advanced panel ----------------------------------------------------

    def _advanced_configured_count(self) -> int:
        count = 0
        for path in _ADVANCED_PATHS:
            try:
                value = self.document.value(path)
            except Exception:
                value = None
            if isinstance(value, list):
                if value:
                    count += 1
            else:
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
            panel = self.query_one("#advanced-network", Collapsible)
        except Exception:
            return
        panel.title = self._advanced_title()
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_visible(self) -> None:
        # Only commit fields relevant to the current mode so switching modes
        # never rewrites the other mode's persisted values.
        for field in self._visible_fields():
            field.commit()

    def _field_errors(self) -> dict[str, str]:
        self._commit_visible()
        errors: dict[str, str] = {}

        for field in self._visible_fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            if "certificate_arn" in lowered:
                errors.setdefault("alb.certificate_arn", error)
            elif "private_subnet" in lowered or "subnet" in lowered:
                errors.setdefault("project.private_subnet_ids", error)
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

    # -- events ------------------------------------------------------------

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        event.field.commit()
        self._apply_mode_visibility()
        self._sync_touched_errors()

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())


__all__ = ["NetworkSection"]
