"""The Storage section: a master-detail editor for S3 buckets (ticket 11).

Buckets are a repeatable resource, so this section reuses
:class:`MasterDetailSection` exactly like Services: a searchable list of buckets
beside :class:`BucketDetail`, the editor for the selected bucket, with Add,
Duplicate, and confirmed Delete. Together they cover every persisted bucket
field — name, mode, the mode-specific existing/seed fields, preview fallback
bucket and env key, public read, CloudFront, CORS, and all connection fields —
editing the document draft directly.

Mode-specific fields live in conditional panels: the existing-bucket name shows
only in ``existing`` mode and the seed-copy fields only in ``seed-copy`` mode.
Values hidden by the current mode are *preserved* in the document (an untouched
control never rewrites the draft), so navigating away and back or performing a
no-op save keeps them. Changing the mode to one incompatible with a value that is
currently set asks for confirmation first and only then clears the incompatible
fields.

Deleting a bucket that other resources still reference is not blocked: Delete
presents the complete impact — the bucket's own service connections and any
service ``s3_access`` grants that name it — and, on confirmation, removes the
bucket and every external grant to it in one reversible document transaction. The
impact inventory and cleanup live in the widget-free
:mod:`darth_infra.config.reference_impact` module.

Public-read is deployment-sensitive: enabling it surfaces an amber warning
describing what a future deploy may do, but it remains ordinary saveable
configuration and is never blocked.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Checkbox, Collapsible, Input, Static

from ...config.reference_impact import (
    bucket_removal_references,
    remove_bucket_with_references,
)
from ..field_registry import registry_entry
from .collection import (
    STATE_INVALID,
    STATE_MODIFIED,
    STATE_OK,
    ConfirmScreen,
    MasterDetailSection,
    NestedCollectionEditor,
)
from .widgets import (
    BooleanField,
    EditableField,
    ServiceSelectField,
    TextField,
    dom_slug,
)

_COLLECTION = "s3_buckets"

_MODE_OPTIONS = [
    ("Create managed bucket", "managed"),
    ("Use existing bucket", "existing"),
    ("Create managed bucket + one-time seed copy", "seed-copy"),
]

# Fields shown only for a particular mode.
_EXISTING_FIELDS = ("existing_bucket_name",)
_SEED_FIELDS = ("seed_source_bucket_name", "seed_non_prod_only")

# Advanced (collapsible) scalar bucket-owned fields covered by this section. The
# mode-specific existing/seed fields are handled by conditional panels instead.
_ADVANCED_FIELDS = (
    "preview_fallback_bucket_name",
    "preview_fallback_env_key",
    "cors",
)

_PUBLIC_READ_WARNING = (
    "⚠ Deployment-sensitive: public read grants anonymous access to this "
    "bucket's objects. A future deploy would apply a public bucket policy. "
    "This stays ordinary saveable configuration."
)


def _bucket_help(field: str) -> str:
    entry = registry_entry(f"s3_buckets[].{field}")
    return entry.help if entry else ""


def _bucket_example(field: str) -> str | None:
    entry = registry_entry(f"s3_buckets[].{field}")
    return entry.example if entry else None


def _conn_help(field: str) -> str:
    entry = registry_entry(f"s3_buckets[].connections[].{field}")
    return entry.help if entry else ""


def _conn_example(field: str) -> str | None:
    entry = registry_entry(f"s3_buckets[].connections[].{field}")
    return entry.example if entry else None


class BucketDetail(Vertical):
    """Editor for a single S3 bucket, bound to ``s3_buckets[<index>]`` paths."""

    class DraftChanged(Message):
        """Posted when a field edit changes the bucket draft."""

    def __init__(self, document: Any, index: int) -> None:
        super().__init__(id=f"bucket-detail-{index}", classes="detail-form")
        self.document = document
        self.index = index
        # The mode currently reflected in the document; a mode change that would
        # clear an incompatible value is only adopted after confirmation, so this
        # lets a cancelled change revert the control.
        self._committed_mode = self._mode_value()
        self._reverting_mode = False

    def _path(self, field: str) -> str:
        return f"{_COLLECTION}[{self.index}].{field}"

    def _mode_value(self) -> str:
        try:
            value = self.document.value(self._path("mode"))
        except Exception:
            value = None
        return str(value) if value else "managed"

    # -- service names -----------------------------------------------------

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
        yield Static("", id="bucket-detail-error", classes="field-error")

        yield TextField(
            field_path=self._path("name"),
            document=self.document,
            label="Bucket name (logical)",
            help=_bucket_help("name"),
            constraints="required; unique across buckets",
            example="media",
            required=True,
        )
        yield _ModeSelectField(
            field_path=self._path("mode"),
            document=self.document,
            label="Bucket mode",
            help=_bucket_help("mode"),
            default_display="managed",
            options=_MODE_OPTIONS,
        )
        yield TextField(
            field_path=self._path("existing_bucket_name"),
            document=self.document,
            label="Existing bucket name",
            help=_bucket_help("existing_bucket_name"),
            constraints="required in existing mode",
            example="my-existing-bucket",
        )
        yield TextField(
            field_path=self._path("seed_source_bucket_name"),
            document=self.document,
            label="Seed source bucket name",
            help=_bucket_help("seed_source_bucket_name"),
            constraints="required in seed-copy mode",
            example="legacy-media-bucket",
        )
        yield BooleanField(
            field_path=self._path("seed_non_prod_only"),
            document=self.document,
            label="Seed only in non-prod environments",
            help=_bucket_help("seed_non_prod_only"),
            default_display="true",
        )
        yield BooleanField(
            field_path=self._path("public_read"),
            document=self.document,
            label="Public read",
            help=_bucket_help("public_read"),
            default_display="false",
        )
        yield Static(
            _PUBLIC_READ_WARNING,
            id=f"bucket-sensitive-{self.index}",
            classes="field-warning",
        )
        yield BooleanField(
            field_path=self._path("cloudfront"),
            document=self.document,
            label="Enable CloudFront",
            help=_bucket_help("cloudfront"),
            default_display="false",
        )

        yield Collapsible(
            *self._advanced_widgets(),
            title=self._advanced_title(),
            id=f"advanced-bucket-{self.index}",
            collapsed=not self._advanced_should_expand(),
        )

        yield self._connections_editor()

    def _advanced_widgets(self) -> list[EditableField]:
        return [
            TextField(
                field_path=self._path("preview_fallback_bucket_name"),
                document=self.document,
                label="Preview fallback bucket name",
                help=_bucket_help("preview_fallback_bucket_name"),
                example=_bucket_example("preview_fallback_bucket_name"),
            ),
            TextField(
                field_path=self._path("preview_fallback_env_key"),
                document=self.document,
                label="Preview fallback env var name",
                help=_bucket_help("preview_fallback_env_key"),
                example=_bucket_example("preview_fallback_env_key"),
            ),
            BooleanField(
                field_path=self._path("cors"),
                document=self.document,
                label="Enable CORS",
                help=_bucket_help("cors"),
                default_display="false",
            ),
        ]

    # -- connections nested collection -------------------------------------

    def _connections_editor(self) -> NestedCollectionEditor:
        service_names = self._service_names()

        def build(base: str) -> list[EditableField]:
            return [
                ServiceSelectField(
                    field_path=f"{base}.service",
                    document=self.document,
                    label="Service",
                    help=_conn_help("service"),
                    eligible=service_names,
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.env_key",
                    document=self.document,
                    label="Bucket env var name",
                    help=_conn_help("env_key"),
                    example=_conn_example("env_key"),
                    required=True,
                ),
                TextField(
                    field_path=f"{base}.cloudfront_env_key",
                    document=self.document,
                    label="CloudFront URL env var name",
                    help=_conn_help("cloudfront_env_key"),
                    constraints="requires CloudFront enabled on this bucket",
                    example="MEDIA_CDN_URL",
                ),
                BooleanField(
                    field_path=f"{base}.read_only",
                    document=self.document,
                    label="Read-only",
                    help=_conn_help("read_only"),
                    default_display="false",
                ),
            ]

        def record_invalid(
            raw: dict[str, Any], index: int, all_raw: list[dict[str, Any]]
        ) -> bool:
            service = str(raw.get("service") or "").strip()
            if not service or service not in service_names:
                return True
            if not str(raw.get("env_key") or "").strip():
                return True
            siblings = [
                str(other.get("service") or "").strip()
                for i, other in enumerate(all_raw)
                if i != index
            ]
            return service in siblings

        def record_label(raw: dict[str, Any], index: int) -> str:
            service = str(raw.get("service") or "").strip() or "(no service)"
            env_key = str(raw.get("env_key") or "").strip() or "(no env var)"
            access = "R" if raw.get("read_only") else "R/W"
            return f"{service} → {env_key} [{access}]"

        return NestedCollectionEditor(
            document=self.document,
            collection_path=self._path("connections"),
            noun="connection",
            title="Service connections",
            build_fields=build,
            record_label=record_label,
            record_invalid=record_invalid,
            new_record=lambda: {"service": "", "env_key": ""},
            empty_message="No service connections configured.",
        )

    def _connections_ed(self) -> NestedCollectionEditor | None:
        try:
            return self.query_one(
                f"#nested-{dom_slug(self._path('connections'))}",
                NestedCollectionEditor,
            )
        except Exception:
            return None

    def on_mount(self) -> None:
        for field in self._fields():
            field.refresh_badge()
        self._committed_mode = self._current_mode()
        self._apply_conditionals()
        self._show_banner(None)

    # -- field access ------------------------------------------------------

    def _fields(self) -> list[EditableField]:
        """Every scalar field this detail owns, excluding nested-connection rows."""
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

    # -- conditional presentation ------------------------------------------

    def _current_mode(self) -> str:
        field = self._field("mode")
        if field is not None:
            value = field.current_value()
            if value:
                return str(value)
        return "managed"

    def _apply_conditionals(self) -> None:
        mode = self._current_mode()
        is_existing = mode == "existing"
        is_seed = mode == "seed-copy"
        for name in _EXISTING_FIELDS:
            field = self._field(name)
            if field is not None:
                field.display = is_existing
        for name in _SEED_FIELDS:
            field = self._field(name)
            if field is not None:
                field.display = is_seed
        self._update_sensitive_warning()

    def _update_sensitive_warning(self) -> None:
        field = self._field("public_read")
        show = bool(field and field.current_value())
        try:
            warning = self.query_one(f"#bucket-sensitive-{self.index}", Static)
        except Exception:
            return
        warning.display = show

    # -- mode change with confirmation -------------------------------------

    def _field_has_value(self, name: str) -> bool:
        field = self._field(name)
        if field is None:
            return False
        value = field.current_value()
        if isinstance(value, bool):
            return value
        return bool(value)

    def _incompatible_for_mode(self, mode: str) -> list[str]:
        """Currently-set field names incompatible with ``mode``.

        Mirrors the model's mode rules: managed forbids existing/seed names,
        existing forbids the seed name and CloudFront, and seed-copy forbids the
        existing name.
        """
        candidates: dict[str, tuple[str, ...]] = {
            "managed": ("existing_bucket_name", "seed_source_bucket_name"),
            "existing": ("seed_source_bucket_name", "cloudfront"),
            "seed-copy": ("existing_bucket_name",),
        }
        return [
            name
            for name in candidates.get(mode, ())
            if self._field_has_value(name)
        ]

    _FIELD_LABELS = {
        "existing_bucket_name": "existing bucket name",
        "seed_source_bucket_name": "seed source bucket name",
        "cloudfront": "CloudFront",
    }

    def _handle_mode_change(self, mode_field: EditableField) -> None:
        if self._reverting_mode:
            self._reverting_mode = False
            return
        new_mode = mode_field.current_value() or "managed"
        if new_mode == self._committed_mode:
            mode_field.commit()
            return
        incompatible = self._incompatible_for_mode(str(new_mode))
        if not incompatible:
            self._adopt_mode(mode_field, str(new_mode), [])
            return

        cleared = ", ".join(self._FIELD_LABELS[name] for name in incompatible)

        def _after(confirmed: bool | None) -> None:
            if confirmed:
                self._adopt_mode(mode_field, str(new_mode), incompatible)
            else:
                self._revert_mode(mode_field)

        self.app.push_screen(
            ConfirmScreen(
                "Change bucket mode?",
                f"Switching to '{new_mode}' will clear: {cleared}. Continue?",
                confirm_label="Change mode",
                confirm_variant="warning",
            ),
            _after,
        )

    def _adopt_mode(
        self, mode_field: EditableField, new_mode: str, incompatible: list[str]
    ) -> None:
        mode_field.commit()
        for name in incompatible:
            self._clear_field(name)
        self._committed_mode = new_mode
        self._apply_conditionals()
        self._sync_touched_errors()
        self.post_message(self.DraftChanged())

    def _revert_mode(self, mode_field: EditableField) -> None:
        self._reverting_mode = True
        for select in mode_field.query("Select"):
            try:
                select.value = self._committed_mode
            except Exception:
                pass
            break
        else:
            self._reverting_mode = False

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
            panel = self.query_one(f"#advanced-bucket-{self.index}", Collapsible)
        except Exception:
            return
        panel.title = self._advanced_title()
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def commit_all(self) -> None:
        for field in self._fields():
            field.commit()
        editor = self._connections_ed()
        if editor is not None:
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
            errors[self._path("name")] = "Bucket name is required"
        elif name in self._sibling_names():
            errors[self._path("name")] = "Bucket name must be unique"

        for field in self._fields():
            message = field.validation_error()
            if message:
                errors.setdefault(field.field_path, message)

        editor = self._connections_ed()
        if editor is not None and editor.has_error():
            errors.setdefault(
                "__section__",
                "Fix the highlighted service connections before saving.",
            )

        result = self.document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            mentions_this = bool(name) and f"'{name}'" in error
            if mentions_this and "existing_bucket_name" in lowered:
                errors.setdefault(self._path("existing_bucket_name"), error)
            elif mentions_this and "seed_source_bucket_name" in lowered:
                errors.setdefault(self._path("seed_source_bucket_name"), error)
            elif mentions_this and "preview_fallback_env_key" in lowered:
                errors.setdefault(self._path("preview_fallback_env_key"), error)
            elif "bucket names must be unique" in lowered:
                errors.setdefault(self._path("name"), error)
            elif mentions_this:
                errors.setdefault("__section__", error)
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
        editor = self._connections_ed()
        if editor is not None and editor.has_error():
            invalid.append(editor)
        self._show_banner(errors.get("__section__"))
        self._refresh_advanced()
        return invalid

    def after_save(self) -> None:
        for field in self._fields():
            field.mark_committed()
            field.refresh_badge()
        editor = self._connections_ed()
        if editor is not None:
            editor.refresh_markers()
        self._refresh_advanced()

    def _show_banner(self, message: str | None) -> None:
        banner = self.query_one("#bucket-detail-error", Static)
        if message:
            banner.update(f"✗ {message}")
            banner.display = True
        else:
            banner.update("")
            banner.display = False

    # -- events ------------------------------------------------------------

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        if event.field.field_path == self._path("mode"):
            self._handle_mode_change(event.field)
            return
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


class _ModeSelectField(EditableField):
    """A dropdown for the bucket mode.

    A dedicated subclass (rather than the shared ``SelectField``) so a mode change
    is intercepted by :class:`BucketDetail` before it commits, letting an
    incompatible switch be confirmed or reverted.
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
            value=current if current is not None else Select.BLANK,
            allow_blank=False,
            id=f"input-{self.slug}",
            classes="field-select",
        )

    def _select(self):
        from textual.widgets import Select

        return self.query_one(f"#input-{self.slug}", Select)

    def current_value(self) -> str | None:
        from textual.widgets import Select

        value = self._select().value
        if value is Select.BLANK:
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


class StorageSection(MasterDetailSection):
    """Searchable master-detail editor for the project's S3 buckets."""

    section_title = "Storage"
    item_noun = "bucket"
    empty_message = "No buckets yet. Add one to get started."

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
        return name if name else "(unnamed bucket)"

    def item_state(self, index: int) -> str:
        name = self._record_name(index)
        names = [self._record_name(i) for i in range(self.item_count())]
        if not name or names.count(name) > 1:
            return STATE_INVALID
        if index in self._modified:
            return STATE_MODIFIED
        return STATE_OK

    def build_detail(self, index: int) -> BucketDetail:
        return BucketDetail(self.document, index)

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
        # One document transaction: the bucket and every external s3_access grant
        # go together, so the whole cascade reverts as a unit until it is saved.
        with self.document.transaction():
            remove_bucket_with_references(self.document, name)
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
        return [ref.description for ref in bucket_removal_references(config, name)]

    # -- modified tracking -------------------------------------------------

    def after_save(self) -> None:
        self._modified.clear()
        super().after_save()

    def on_bucket_detail_draft_changed(
        self, event: BucketDetail.DraftChanged
    ) -> None:
        event.stop()
        if self._selected is not None:
            self._modified.add(self._selected)
        self._refresh_list()


__all__ = ["StorageSection", "BucketDetail"]
