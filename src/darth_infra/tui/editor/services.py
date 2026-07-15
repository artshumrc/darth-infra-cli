"""The Services section: a master-detail editor for ECS services.

This is the first concrete use of :class:`MasterDetailSection`. The section owns
the list of services and the Add/Duplicate/Delete workflow;
:class:`ServiceDetail` is the editor for one selected service. Together they
cover every persisted service setting — common container, build, compute, health,
launch, and environment-variable settings, plus the advanced architecture,
user-data, ECS Exec, SES, service-discovery, ulimit, and EBS-volume settings —
directly in the document draft, with no separate Add-versus-Update mode.

Deleting a service that other resources still reference is not blocked: the
Delete action presents the complete impact list and, on confirmation, removes the
service and every external reference to it in one reversible document
transaction. The impact inventory and cleanup live in the widget-free
:mod:`darth_infra.config.reference_impact` module.

The global Cloud Map service-discovery namespace is owned by this section (the
per-service registration toggle stays on each service).
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Input, Static

from ...config.reference_impact import (
    delete_service_with_references,
    external_service_references,
)
from ..field_registry import registry_entry
from .collection import (
    STATE_INVALID,
    STATE_MODIFIED,
    STATE_OK,
    MasterDetailSection,
    NestedCollectionEditor,
)
from .widgets import (
    BooleanField,
    EditableField,
    IntegerField,
    KeyValueMapField,
    OptionalSelectField,
    SelectField,
    TextAreaField,
    TextField,
    dom_slug,
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
# EC2-only fields/panels: hidden or unavailable for Fargate services.
_EC2_ONLY_FIELDS = (
    "ec2_instance_type",
    "architecture",
    "user_data_script",
    "user_data_script_content",
)
# Advanced (collapsible) scalar service-owned fields covered by this slice.
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
    "enable_service_discovery",
    "ec2_instance_type",
    "architecture",
    "user_data_script",
    "user_data_script_content",
)
# Nested advanced collections owned by a service.
_ADVANCED_COLLECTIONS = ("ulimits", "ebs_volumes")

# Enum option sets, mirrored from the persisted schema.
_ULIMIT_NAMES = (
    "core", "cpu", "data", "fsize", "locks", "memlock", "msgqueue", "nice",
    "nofile", "nproc", "rss", "rtprio", "rttime", "sigpending", "stack",
)
_ULIMIT_OPTIONS = [(name, name) for name in _ULIMIT_NAMES]
_EBS_VOLUME_TYPES = [(v, v) for v in ("gp2", "gp3", "io1", "io2", "st1", "sc1")]
_EBS_FILESYSTEMS = [(v, v) for v in ("ext4", "xfs")]
_ARCHITECTURES = [("x86_64", "x86_64"), ("arm64", "arm64")]


def _help(field: str) -> str:
    entry = registry_entry(f"services[].{field}")
    return entry.help if entry else ""


def _example(field: str) -> str | None:
    entry = registry_entry(f"services[].{field}")
    return entry.example if entry else None


def _nested_help(path: str) -> str:
    entry = registry_entry(path)
    return entry.help if entry else ""


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

    def _advanced_fields_widgets(self) -> list[Any]:
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
            BooleanField(
                field_path=self._path("enable_service_discovery"),
                document=self.document,
                label="Register with service discovery",
                help=_help("enable_service_discovery"),
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
            OptionalSelectField(
                field_path=self._path("architecture"),
                document=self.document,
                label="CPU architecture",
                help=_help("architecture"),
                constraints="Automatic infers it from the EC2 instance type",
                example=_example("architecture"),
                options=_ARCHITECTURES,
            ),
            TextField(
                field_path=self._path("user_data_script"),
                document=self.document,
                label="User-data script path",
                help=_help("user_data_script"),
            ),
            TextAreaField(
                field_path=self._path("user_data_script_content"),
                document=self.document,
                label="Inline user-data script",
                help=_help("user_data_script_content"),
            ),
            self._ulimits_editor(),
            self._ebs_editor(),
        ]

    # -- nested collections ------------------------------------------------

    def _ulimits_editor(self) -> NestedCollectionEditor:
        def build(base: str) -> list[EditableField]:
            return [
                SelectField(
                    field_path=f"{base}.name",
                    document=self.document,
                    label="Ulimit name",
                    help=_nested_help("services[].ulimits[].name"),
                    options=_ULIMIT_OPTIONS,
                    required=True,
                ),
                IntegerField(
                    field_path=f"{base}.soft_limit",
                    document=self.document,
                    label="Soft limit",
                    help=_nested_help("services[].ulimits[].soft_limit"),
                    required=True,
                ),
                IntegerField(
                    field_path=f"{base}.hard_limit",
                    document=self.document,
                    label="Hard limit",
                    help=_nested_help("services[].ulimits[].hard_limit"),
                    required=True,
                ),
            ]

        return NestedCollectionEditor(
            document=self.document,
            collection_path=self._path("ulimits"),
            noun="ulimit",
            title="Ulimits",
            build_fields=build,
            record_label=lambda raw, i: str(raw.get("name") or "(unnamed ulimit)"),
            record_invalid=_ulimit_invalid,
            new_record=lambda: {
                "name": "nofile",
                "soft_limit": 65536,
                "hard_limit": 65536,
            },
            empty_message="No ulimits configured.",
        )

    def _ebs_editor(self) -> NestedCollectionEditor:
        def build(base: str) -> list[EditableField]:
            return [
                TextField(
                    field_path=f"{base}.name",
                    document=self.document,
                    label="Volume name",
                    help=_nested_help("services[].ebs_volumes[].name"),
                    required=True,
                ),
                IntegerField(
                    field_path=f"{base}.size_gb",
                    document=self.document,
                    label="Size (GiB)",
                    help=_nested_help("services[].ebs_volumes[].size_gb"),
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.mount_path",
                    document=self.document,
                    label="Mount path",
                    help=_nested_help("services[].ebs_volumes[].mount_path"),
                    example="/data",
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.device_name",
                    document=self.document,
                    label="Device name",
                    help=_nested_help("services[].ebs_volumes[].device_name"),
                    default_display="/dev/xvdf",
                ),
                SelectField(
                    field_path=f"{base}.volume_type",
                    document=self.document,
                    label="Volume type",
                    help=_nested_help("services[].ebs_volumes[].volume_type"),
                    default_display="gp3",
                    options=_EBS_VOLUME_TYPES,
                ),
                SelectField(
                    field_path=f"{base}.filesystem_type",
                    document=self.document,
                    label="Filesystem",
                    help=_nested_help("services[].ebs_volumes[].filesystem_type"),
                    default_display="ext4",
                    options=_EBS_FILESYSTEMS,
                ),
            ]

        return NestedCollectionEditor(
            document=self.document,
            collection_path=self._path("ebs_volumes"),
            noun="EBS volume",
            title="EBS volumes (EC2 only)",
            build_fields=build,
            record_label=lambda raw, i: str(raw.get("name") or "(unnamed volume)"),
            record_invalid=_ebs_invalid,
            new_record=lambda: {"name": "", "size_gb": 20, "mount_path": ""},
            empty_message="No EBS volumes configured.",
        )

    def _nested_editors(self) -> list[NestedCollectionEditor]:
        return list(self.query(NestedCollectionEditor))

    def on_mount(self) -> None:
        for field in self._fields():
            field.refresh_badge()
        self._apply_conditionals()
        self._show_banner(None)

    # -- field access ------------------------------------------------------

    def _fields(self) -> list[EditableField]:
        """Every editable field this detail owns, excluding nested-collection rows.

        Nested ulimit/EBS row fields belong to their :class:`NestedCollectionEditor`
        and are committed and validated through it, not as direct service fields.
        """
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
        for name in _EC2_ONLY_FIELDS:
            field = self._field(name)
            if field is not None:
                field.display = is_ec2
        ebs = self._nested_editor("ebs_volumes")
        if ebs is not None:
            ebs.display = is_ec2

    def _nested_editor(self, collection: str) -> NestedCollectionEditor | None:
        try:
            return self.query_one(
                f"#nested-{dom_slug(self._path(collection))}",
                NestedCollectionEditor,
            )
        except Exception:
            return None

    # -- advanced panel ----------------------------------------------------

    def _advanced_configured_count(self) -> int:
        count = 0
        for name in _ADVANCED_FIELDS:
            try:
                if self.document.is_explicit(self._path(name)):
                    count += 1
            except Exception:
                pass
        for collection in _ADVANCED_COLLECTIONS:
            try:
                if self.document.record_count(self._path(collection)) > 0:
                    count += 1
            except Exception:
                pass
        return count

    def _advanced_title(self) -> str:
        return f"Advanced ({self._advanced_configured_count()} configured)"

    def _advanced_has_error(self) -> bool:
        if any(
            (f := self._field(name)) is not None and f.error
            for name in _ADVANCED_FIELDS
        ):
            return True
        return any(editor.has_error() for editor in self._nested_editors())

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
        for editor in self._nested_editors():
            editor.commit_all()

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

        # Invalid nested rows are surfaced as a section-level error.
        if any(editor.has_error() for editor in self._nested_editors()):
            errors.setdefault(
                "__section__",
                "Fix the highlighted ulimits / EBS volumes before saving.",
            )

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
        for editor in self._nested_editors():
            if editor.has_error():
                invalid.append(editor)
        self._show_banner(errors.get("__section__"))
        self._refresh_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._fields():
            field.mark_committed()
            field.refresh_badge()
        for editor in self._nested_editors():
            editor.refresh_markers()
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

    def on_nested_collection_editor_changed(
        self, event: NestedCollectionEditor.Changed
    ) -> None:
        event.stop()
        self._sync_touched_errors()
        self.post_message(self.DraftChanged())


def _ulimit_invalid(
    raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
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
    for key in ("soft_limit", "hard_limit"):
        value = raw.get(key)
        if not isinstance(value, int):
            return True
    return False


def _ebs_invalid(
    raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
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
    if not isinstance(raw.get("size_gb"), int):
        return True
    if not str(raw.get("mount_path") or "").strip():
        return True
    return False


class ServicesSection(MasterDetailSection):
    """Searchable master-detail editor for the project's ECS services."""

    section_title = "Services"
    item_noun = "service"
    empty_message = "No services yet. Add one to get started."

    def __init__(self, document: Any) -> None:
        super().__init__(document)
        self._modified: set[int] = set()

    # -- composition (adds the section-owned global namespace field) --------

    def compose(self) -> ComposeResult:
        yield from super().compose()
        ns = registry_entry("service_discovery.namespace_template")
        yield Collapsible(
            TextField(
                field_path="service_discovery.namespace_template",
                document=self.document,
                label="Service discovery namespace",
                help=ns.help if ns else "",
                default_display="local",
                example=ns.example if ns else None,
            ),
            title="Service discovery namespace (global)",
            id="services-global-namespace",
            collapsed=not self._namespace_configured(),
        )

    def _namespace_configured(self) -> bool:
        try:
            return bool(
                self.document.is_explicit("service_discovery.namespace_template")
            )
        except Exception:
            return False

    def _namespace_field(self) -> EditableField | None:
        try:
            return self.query_one(
                "#field-service-discovery-namespace-template", EditableField
            )
        except Exception:
            return None

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
        self._reindex_after_delete(index)

    def cascade_delete(self, index: int) -> None:
        name = self._record_name(index)
        # One document transaction: the record and every external reference go
        # together, so the whole cascade reverts as a unit until it is saved.
        with self.document.transaction():
            delete_service_with_references(self.document, name)
        self._reindex_after_delete(index)

    def _reindex_after_delete(self, index: int) -> None:
        self._modified = {
            (i if i < index else i - 1)
            for i in self._modified
            if i != index
        }

    def blocking_references(self, index: int) -> list[str]:
        # A draft that will not parse cannot be scanned for references; block the
        # delete rather than risk leaving a dangling reference.
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
        return [ref.description for ref in external_service_references(config, name)]

    # -- section-level validation / save -----------------------------------

    def validate_all(self) -> list:
        invalid = super().validate_all()
        ns = self._namespace_field()
        if ns is not None:
            ns.commit()
        return invalid

    def after_save(self) -> None:
        self._modified.clear()
        ns = self._namespace_field()
        if ns is not None:
            ns.mark_committed()
            ns.refresh_badge()
        super().after_save()

    # -- modified tracking -------------------------------------------------

    def on_service_detail_draft_changed(
        self, event: ServiceDetail.DraftChanged
    ) -> None:
        event.stop()
        if self._selected is not None:
            self._modified.add(self._selected)
        self._refresh_list()

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        # Only the section-owned namespace field reaches here; per-service field
        # events are stopped inside their ServiceDetail.
        event.stop()
        event.field.commit()

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()


__all__ = ["ServicesSection", "ServiceDetail"]
