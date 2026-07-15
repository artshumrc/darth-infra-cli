"""Section content widgets for the Guided editor.

Each canonical navigation destination renders a *section*. This slice ships the
functional :class:`ProjectSection`; the remaining destinations render a
:class:`PlaceholderSection` so navigation is complete without pretending the
editor is finished. Later tickets replace placeholders with real sections
without changing the shell's navigation interface.

The Project section owns validation presentation: it commits field edits into
the :class:`~darth_infra.config.document.ProjectDocument`, validates the draft
through the existing model semantics, and pushes adjacent errors onto the
touched fields that own them. Untouched fields never show errors; once a field
is showing an error, the section clears it live as soon as it is fixed.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Static

from ..field_registry import Section, registry_entry
from .navigation import SECTION_LABELS
from .widgets import (
    EditableField,
    KeyValueMapField,
    ReadOnlyField,
    StringListField,
    TextField,
)


class PlaceholderSection(VerticalScroll):
    """Content for a navigation destination not yet implemented in this slice."""

    def __init__(self, section: Section) -> None:
        super().__init__(id="section-content", classes="section-content placeholder-section")
        self._section = section

    def compose(self) -> ComposeResult:
        label = SECTION_LABELS[self._section]
        yield Static(label, classes="section-title")
        yield Static(
            f"The {label} section is not available yet.",
            classes="placeholder-message",
        )
        yield Static(
            "It is coming in a later slice of the configuration editor.",
            classes="field-help",
        )


class ProjectSection(VerticalScroll):
    """Functional editor for project identity, region, environments, and tags."""

    # Advanced field paths owned by this section. Kept explicit so the Advanced
    # panel's configured-count and auto-expand can be computed from the document
    # during compose, before the panel widget itself exists.
    _ADVANCED_PATHS: tuple[str, ...] = ("project.tags",)

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content")
        self._document = document

    # -- composition -------------------------------------------------------

    class SaveContinueRequested(Message):
        """Posted when the section's Save & Continue action is pressed."""

    def compose(self) -> ComposeResult:
        yield Static("Project", classes="section-title")
        yield Static("", id="section-error", classes="field-error")

        name = registry_entry("project.name")
        yield TextField(
            field_path="project.name",
            document=self._document,
            label="Project name",
            help=name.help if name else "",
            constraints="kebab-case; required",
            example=name.example if name else None,
            required=True,
        )

        region = registry_entry("project.aws_region")
        yield TextField(
            field_path="project.aws_region",
            document=self._document,
            label="AWS region",
            help=region.help if region else "",
            default_display="us-east-1",
            example=region.example if region else None,
        )

        environments = registry_entry("project.environments")
        yield StringListField(
            field_path="project.environments",
            document=self._document,
            label="Environments",
            help=environments.help if environments else "",
            default_display="prod",
            constraints="comma-separated; 'prod' must be included",
            example=environments.example if environments else None,
        )

        yield ReadOnlyField(
            field_path="project.cli_version_floor",
            document=self._document,
            label="CLI version floor",
            help=(
                "Minimum darth-infra CLI version allowed for this project. "
                "Maintained by the CLI; shown for inspection only."
            ),
        )

        tags = registry_entry("project.tags.*")
        tags_field = KeyValueMapField(
            field_path="project.tags",
            document=self._document,
            label="Project tags",
            help=tags.help if tags else "",
            example=tags.example if tags else None,
        )
        yield Collapsible(
            tags_field,
            title=self._advanced_title(),
            id="advanced-project",
            collapsed=not self._advanced_should_expand(),
        )

        yield Button(
            "Save & Continue",
            id="save-continue",
            variant="primary",
        )

    def on_mount(self) -> None:
        # Reflect initial explicit/default state on every badge.
        for field in self._editable_fields():
            field.refresh_badge()
        self._show_section_error(None)

    # -- field access ------------------------------------------------------

    def _editable_fields(self) -> list[EditableField]:
        return list(self.query(EditableField))

    def _advanced_fields(self) -> list[EditableField]:
        panel = self.query_one("#advanced-project", Collapsible)
        return list(panel.query(EditableField))

    # -- advanced panel ----------------------------------------------------

    def _advanced_configured_count(self) -> int:
        """Number of configured advanced fields, computed from the document.

        A map field counts when it holds any entry; a scalar field counts when
        it is explicitly present. Computed from the document (not mounted
        widgets) so it is valid during compose.
        """
        count = 0
        for path in self._ADVANCED_PATHS:
            try:
                value = self._document.value(path)
            except Exception:
                value = None
            if isinstance(value, dict):
                if value:
                    count += 1
            else:
                try:
                    if self._document.is_explicit(path):
                        count += 1
                except Exception:
                    pass
        return count

    def _advanced_has_error(self) -> bool:
        try:
            fields = self._advanced_fields()
        except Exception:
            return False
        return any(field.error for field in fields)

    def _advanced_title(self) -> str:
        return f"Advanced ({self._advanced_configured_count()} configured)"

    def _advanced_should_expand(self) -> bool:
        return self._advanced_configured_count() > 0 or self._advanced_has_error()

    def _refresh_advanced(self) -> None:
        panel = self.query_one("#advanced-project", Collapsible)
        panel.title = self._advanced_title()
        # Auto-expand for configured values or errors; never force-collapse.
        if self._advanced_should_expand():
            panel.collapsed = False

    # -- validation --------------------------------------------------------

    def _commit_all(self) -> None:
        for field in self._editable_fields():
            field.commit()

    def _field_errors(self) -> dict[str, str]:
        """Compute adjacent errors, keyed by field path, for the current draft."""
        self._commit_all()
        errors: dict[str, str] = {}

        # Field-level required checks come first: they give a clearer message
        # than the raw model/loader error for a missing required value.
        for field in self._editable_fields():
            if getattr(field, "required", False):
                value = field.current_value()
                if value in (None, "", [], {}):
                    errors[field.field_path] = f"{field.label} is required"

        result = self._document.validate()
        if not result.ok and result.error:
            error = result.error
            lowered = error.lower()
            if "environments" in lowered or "prod" in lowered:
                errors.setdefault("project.environments", error)
            elif "cli_version_floor" in lowered:
                errors.setdefault("project.cli_version_floor", error)
            elif "region" in lowered:
                errors.setdefault("project.aws_region", error)
            else:
                # A cross-field/model error not attributable to a Project field
                # in this slice; surface it as a section banner.
                errors.setdefault("__section__", error)
        return errors

    def _sync_touched_errors(self) -> None:
        """Update error displays for touched fields only, clearing fixed ones."""
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

    def _show_section_error(self, message: str | None) -> None:
        banner = self.query_one("#section-error", Static)
        if message:
            banner.update(f"✗ {message}")
            banner.display = True
        else:
            banner.update("")
            banner.display = False

    def validate_all(self) -> list[EditableField]:
        """Validate for a save attempt.

        Marks every offending field touched, shows its error, and returns the
        invalid fields in document order (first is the one to focus).
        """
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

    # -- event handlers ----------------------------------------------------

    def on_editable_field_blurred(self, event: EditableField.Blurred) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_editable_field_changed(self, event: EditableField.Changed) -> None:
        event.stop()
        self._sync_touched_errors()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-continue":
            event.stop()
            self.post_message(self.SaveContinueRequested())


__all__ = ["ProjectSection", "PlaceholderSection"]
