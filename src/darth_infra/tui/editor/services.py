"""The Services section: a master-detail editor for ECS services.

This is the first concrete use of :class:`MasterDetailSection`. The section owns
the list of services and the Add/Duplicate/Delete workflow; :class:`ServiceDetail`
is the editor for one selected service. Together they cover the common container,
build, compute, health, launch, and environment-variable settings directly in the
document draft, with no separate Add-versus-Update mode.

Advanced settings that belong to later slices — user data, architecture, ulimits,
EBS volumes, service discovery, and cross-resource references (secrets, S3 access)
— are intentionally not edited here; they arrive in ticket 07 and are preserved
untouched in the meantime.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Input, Static

from ..field_registry import registry_entry
from .collection import STATE_INVALID, STATE_MODIFIED, STATE_OK, MasterDetailSection
from .widgets import (
    BooleanField,
    EditableField,
    IntegerField,
    KeyValueMapField,
    SelectField,
    TextField,
)

_COLLECTION = "services"

# Docker-build fields hidden when an external image is supplied.
_BUILD_FIELDS = ("dockerfile", "build_context", "docker_build_target")
# Health-check fields hidden for background workers (services with no port).
_HEALTH_FIELDS = (
    "health_check_path",
    "health_check_http_codes",
    "health_check_timeout_seconds",
    "health_check_interval_seconds",
    "healthy_threshold_count",
    "unhealthy_threshold_count",
    "health_check_grace_period_seconds",
)
# Advanced (collapsible) service-owned fields covered by this slice.
_ADVANCED_FIELDS = (
    "build_context",
    "docker_build_target",
    "health_check_http_codes",
    "health_check_timeout_seconds",
    "health_check_interval_seconds",
    "healthy_threshold_count",
    "unhealthy_threshold_count",
    "health_check_grace_period_seconds",
    "command",
    "enable_exec",
    "enable_ses_send_email",
    "ec2_instance_type",
)


def _help(field: str) -> str:
    entry = registry_entry(f"services[].{field}")
    return entry.help if entry else ""


def _example(field: str) -> str | None:
    entry = registry_entry(f"services[].{field}")
    return entry.example if entry else None


class ServiceDetail(Vertical):
    """Editor for a single service, bound to ``services[<index>]`` paths."""

    class DraftChanged(Message):
        """Posted when a field edit changes the service draft."""

    def __init__(self, document: Any, index: int) -> None:
        super().__init__(id=f"service-detail-{index}", classes="detail-form")
        self.document = document
        self.index = index

    def _path(self, field: str) -> str:
        return f"{_COLLECTION}[{self.index}].{field}"

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="service-detail-error", classes="field-error")

        yield TextField(
            field_path=self._path("name"),
            document=self.document,
            label="Service name",
            help=_help("name"),
            constraints="required; unique across services",
            example=_example("name"),
            required=True,
        )
        yield TextField(
            field_path=self._path("image"),
            document=self.document,
            label="External image",
            help=_help("image"),
            constraints="when set, Docker build is skipped",
            example=_example("image"),
        )
        yield TextField(
            field_path=self._path("dockerfile"),
            document=self.document,
            label="Dockerfile",
            help=_help("dockerfile"),
            default_display="Dockerfile",
        )
        yield IntegerField(
            field_path=self._path("port"),
            document=self.document,
            label="Container port",
            help=_help("port"),
            constraints="leave empty for a background worker",
            default_display="8000",
        )
        yield TextField(
            field_path=self._path("health_check_path"),
            document=self.document,
            label="Health check path",
            help=_help("health_check_path"),
            default_display="/health",
        )
        yield IntegerField(
            field_path=self._path("cpu"),
            document=self.document,
            label="CPU units",
            help=_help("cpu"),
            default_display="256",
        )
        yield IntegerField(
            field_path=self._path("memory_mib"),
            document=self.document,
            label="Memory (MiB)",
            help=_help("memory_mib"),
            default_display="512",
        )
        yield IntegerField(
            field_path=self._path("desired_count"),
            document=self.document,
            label="Desired count",
            help=_help("desired_count"),
            default_display="1",
        )
        yield SelectField(
            field_path=self._path("launch_type"),
            document=self.document,
            label="Launch type",
            help=_help("launch_type"),
            default_display="fargate",
            options=[("Fargate", "fargate"), ("EC2", "ec2")],
        )

        env = registry_entry("services[].environment_variables.*")
        yield KeyValueMapField(
            field_path=self._path("environment_variables"),
            document=self.document,
            label="Environment variables",
            help=env.help if env else "",
            example=env.example if env else None,
        )

        yield Collapsible(
            *self._advanced_fields_widgets(),
            title=self._advanced_title(),
            id=f"advanced-service-{self.index}",
            collapsed=not self._advanced_should_expand(),
        )

    def _advanced_fields_widgets(self) -> list[EditableField]:
        return [
            TextField(
                field_path=self._path("build_context"),
                document=self.document,
                label="Build context",
                help=_help("build_context"),
                default_display=".",
            ),
            TextField(
                field_path=self._path("docker_build_target"),
                document=self.document,
                label="Docker build target",
                help=_help("docker_build_target"),
                example=_example("docker_build_target"),
            ),
            TextField(
                field_path=self._path("health_check_http_codes"),
                document=self.document,
                label="Health check success codes",
                help=_help("health_check_http_codes"),
                default_display="200-399",
            ),
            IntegerField(
                field_path=self._path("health_check_timeout_seconds"),
                document=self.document,
                label="Health check timeout (s)",
                help=_help("health_check_timeout_seconds"),
                default_display="5",
            ),
            IntegerField(
                field_path=self._path("health_check_interval_seconds"),
                document=self.document,
                label="Health check interval (s)",
                help=_help("health_check_interval_seconds"),
                default_display="30",
            ),
            IntegerField(
                field_path=self._path("healthy_threshold_count"),
                document=self.document,
                label="Healthy threshold",
                help=_help("healthy_threshold_count"),
                default_display="5",
            ),
            IntegerField(
                field_path=self._path("unhealthy_threshold_count"),
                document=self.document,
                label="Unhealthy threshold",
                help=_help("unhealthy_threshold_count"),
                default_display="2",
            ),
            IntegerField(
                field_path=self._path("health_check_grace_period_seconds"),
                document=self.document,
                label="Health check grace period (s)",
                help=_help("health_check_grace_period_seconds"),
            ),
            TextField(
                field_path=self._path("command"),
                document=self.document,
                label="Command override",
                help=_help("command"),
            ),
            BooleanField(
                field_path=self._path("enable_exec"),
                document=self.document,
                label="Enable ECS Exec",
                help=_help("enable_exec"),
                default_display="true",
            ),
            BooleanField(
                field_path=self._path("enable_ses_send_email"),
                document=self.document,
                label="Allow sending email via SES",
                help=_help("enable_ses_send_email"),
                default_display="false",
            ),
            TextField(
                field_path=self._path("ec2_instance_type"),
                document=self.document,
                label="EC2 instance type",
                help=_help("ec2_instance_type"),
                constraints="required when launch type is EC2",
                example=_example("ec2_instance_type"),
            ),
        ]

    def on_mount(self) -> None:
        for field in self._fields():
            field.refresh_badge()
        self._apply_conditionals()
        self._show_banner(None)

    # -- field access ------------------------------------------------------

    def _fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def _field(self, field: str) -> EditableField | None:
        try:
            return self.query_one(
                f"#field-{_slug(self._path(field))}", EditableField
            )
        except Exception:
            return None

    def focus_first(self) -> None:
        field = self._field("name")
        if field is not None:
            inputs = field.query(Input)
            if inputs:
                inputs.first().focus()

    # -- conditional presentation -----------------------------------------

    def _apply_conditionals(self) -> None:
        image_field = self._field("image")
        has_image = bool(image_field and image_field.current_value())
        for name in _BUILD_FIELDS:
            field = self._field(name)
            if field is not None:
                field.display = not has_image

        port_field = self._field("port")
        is_worker = not (port_field and port_field.current_value() is not None)
        for name in _HEALTH_FIELDS:
            field = self._field(name)
            if field is not None:
                field.display = not is_worker

        launch = self._field("launch_type")
        is_ec2 = bool(launch and launch.current_value() == "ec2")
        ec2_field = self._field("ec2_instance_type")
        if ec2_field is not None:
            ec2_field.display = is_ec2

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
            panel = self.query_one(f"#advanced-service-{self.index}", Collapsible)
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
            errors[self._path("name")] = "Service name is required"
        elif name in self._sibling_names():
            errors[self._path("name")] = "Service name must be unique"

        # Local format errors (for example non-integer input) come next.
        for field in self._fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            mentions_this = bool(name) and name in error
            if mentions_this and (
                "ec2_instance_type" in lowered or "ec2 launch type" in lowered
            ):
                errors.setdefault(self._path("ec2_instance_type"), error)
            elif mentions_this and "ebs_volumes" in lowered:
                errors.setdefault("__section__", error)
            elif "service names must be unique" in lowered:
                errors.setdefault(self._path("name"), error)
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

    def validate_for_save(self) -> list[EditableField]:
        errors = self._field_errors()
        invalid: list[EditableField] = []
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
        banner = self.query_one("#service-detail-error", Static)
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
        self._apply_conditionals()
        self._sync_touched_errors()
        self.post_message(self.DraftChanged())

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()


def _slug(field_path: str) -> str:
    from .widgets import dom_slug

    return dom_slug(field_path)


class ServicesSection(MasterDetailSection):
    """Searchable master-detail editor for the project's ECS services."""

    section_title = "Services"
    item_noun = "service"
    empty_message = "No services yet. Add one to get started."

    def __init__(self, document: Any) -> None:
        super().__init__(document)
        self._modified: set[int] = set()

    # -- record metadata ---------------------------------------------------

    def item_count(self) -> int:
        return self.document.record_count(_COLLECTION)

    def _record_name(self, index: int) -> str:
        return str(self.document.raw_record(_COLLECTION, index).get("name", ""))

    def item_label(self, index: int) -> str:
        name = self._record_name(index)
        return name if name else "(unnamed service)"

    def item_state(self, index: int) -> str:
        name = self._record_name(index)
        names = [self._record_name(i) for i in range(self.item_count())]
        if not name or names.count(name) > 1:
            return STATE_INVALID
        if index in self._modified:
            return STATE_MODIFIED
        return STATE_OK

    def build_detail(self, index: int) -> ServiceDetail:
        return ServiceDetail(self.document, index)

    # -- add / duplicate / delete ------------------------------------------

    def create_record(self) -> int:
        return self.document.add_record(_COLLECTION, {"name": ""})

    def duplicate_record(self, index: int) -> int:
        values = self.document.raw_record(_COLLECTION, index)
        values["name"] = ""
        return self.document.add_record(_COLLECTION, values)

    def delete_record(self, index: int) -> None:
        self.document.remove_record(_COLLECTION, index)
        self._modified = {
            (i if i < index else i - 1)
            for i in self._modified
            if i != index
        }

    def blocking_references(self, index: int) -> list[str]:
        name = self._record_name(index)
        if not name:
            return []
        try:
            config = self.document.config
        except Exception:
            # A draft that will not parse cannot be scanned for references;
            # block deletion rather than risk leaving a dangling reference.
            return ["configuration errors elsewhere (resolve them first)"]

        refs: list[str] = []
        alb = config.alb
        if getattr(alb, "default_target_service", None) == name:
            refs.append("the ALB default target service")
        for rule in getattr(alb, "path_rules", []) or []:
            if rule.target_service == name:
                refs.append(f"ALB path rule '{rule.name}'")
        rds = getattr(config, "rds", None)
        if rds and name in (rds.expose_to or []):
            refs.append("the database's expose_to list")
        for conn in getattr(config.cloudfront, "connections", []) or []:
            if conn.service == name:
                refs.append(f"CloudFront connection '{conn.env_key}'")
        for bucket in getattr(config, "s3_buckets", []) or []:
            for conn in bucket.connections or []:
                if conn.service == name:
                    refs.append(f"S3 bucket '{bucket.name}' access")
        return refs

    # -- modified tracking -------------------------------------------------

    def on_service_detail_draft_changed(
        self, event: ServiceDetail.DraftChanged
    ) -> None:
        event.stop()
        if self._selected is not None:
            self._modified.add(self._selected)
        self._refresh_list()

    def after_save(self) -> None:
        self._modified.clear()
        super().after_save()


__all__ = ["ServicesSection", "ServiceDetail"]
