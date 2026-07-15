"""The Guided configuration editor application shell.

This is the non-linear, document-preserving editor introduced by the
``tui-configuration-editor`` epic. It is driven entirely by a
:class:`~darth_infra.config.document.ProjectDocument` and presents the nine
canonical navigation destinations, all of which are functional editors.

It is the single TUI architecture: ``darth-infra tui`` opens an existing project
for document-preserving editing and ``darth-infra init`` opens it in creation
mode for first-run scaffolding.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable

from textual import events
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Static

from ..field_registry import Section
from ...config.deploy_risk import DeployRisk, deployment_sensitive_changes
from ...config.document import (
    DocumentConflictError,
    DocumentValidationError,
    ProjectDocument,
)
from .navigation import (
    IMPLEMENTED_SECTIONS,
    SECTION_LABELS,
    SECTION_ORDER,
    nav_button_id,
)
from .aws_discovery import AwsDiscovery, OfflineAwsDiscovery
from .collection import ConfirmScreen
from .database import DatabaseSection
from .environments import EnvironmentsSection
from .network import NetworkSection
from .review import ReviewSection, RiskConfirmScreen, complete_validation_problems
from .routing import RoutingSection
from .sections import PlaceholderSection, ProjectSection
from .secrets import SecretsSection
from .services import ServicesSection
from .session import ConflictResolverScreen, MergePreviewScreen, QuitDecisionScreen
from .storage import StorageSection
from .theme import CONTROL_ROOM_THEME, THEME_NAME
from .widgets import EditableField


# The document paths each section owns for a scoped "Revert this section".
# Project and Network both live under the ``[project]`` table, so their targets
# are listed field-by-field rather than as the shared table. Collection-owning
# sections list their whole array-of-tables so an added or removed record is
# restored too. A whole-session revert (Revert all) always restores everything,
# including cross-section cascading deletions.
_SECTION_REVERT_TARGETS: dict[Section, tuple[str, ...]] = {
    Section.PROJECT: (
        "project.name",
        "project.aws_region",
        "project.environments",
        "project.cli_version_floor",
        "project.tags",
    ),
    Section.NETWORK: (
        "project.vpc_name",
        "project.vpc_id",
        "project.private_subnet_ids",
        "project.public_subnet_ids",
        "project.architecture",
    ),
    Section.SERVICES: ("services", "service_discovery"),
    Section.ROUTING: ("alb", "cloudfront"),
    Section.DATABASE: ("rds",),
    Section.STORAGE: ("s3_buckets",),
    Section.SECRETS: ("secrets",),
    Section.ENVIRONMENTS: ("environments", "preview_environments"),
}

# Minimum usable terminal size. Below this the editor refuses to render a broken
# form and shows a minimum-size message instead.
MIN_WIDTH = 80
MIN_HEIGHT = 24


class FieldHelpScreen(ModalScreen[None]):
    """Expanded, F1-triggered help for the focused field."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=True)]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="field-help-dialog"):
            yield Static(self._title, id="field-help-title", classes="section-title")
            yield Static(self._body, id="field-help-body")
            yield Button("Close", id="field-help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "field-help-close":
            self.dismiss(None)

    def action_dismiss(self, result: Any = None) -> None:
        self.dismiss(None)


class ConfigEditorApp(App[None]):
    """Non-linear, document-preserving Guided editor for a project document."""

    CSS = """
    Screen {
        background: $background;
    }
    #too-small {
        display: none;
        align: center middle;
        width: 100%;
        height: 100%;
        color: $warning;
        text-align: center;
    }
    #editor-main {
        width: 100%;
        height: 1fr;
    }
    #nav-rail {
        width: 22;
        height: 100%;
        border-right: solid $panel;
        padding: 1 1;
        background: $surface;
    }
    #nav-rail .nav-heading {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #nav-rail Button {
        width: 100%;
        margin-bottom: 0;
        border: none;
        height: 1;
    }
    .nav-active {
        color: $accent;
        text-style: bold;
    }
    .nav-unavailable {
        color: $text-muted;
    }
    #content-host {
        width: 1fr;
        height: 100%;
        padding: 1 2;
    }
    .section-content {
        width: 100%;
        height: 100%;
    }
    .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .section-subtitle {
        text-style: bold;
        margin-bottom: 1;
    }
    .editable-field {
        height: auto;
        margin-bottom: 1;
        border-left: solid $panel;
        padding: 0 1;
    }
    .editable-field.field-invalid {
        border-left: solid $error;
    }
    .field-label-row {
        height: auto;
        width: 100%;
    }
    .field-label {
        text-style: bold;
        width: 1fr;
    }
    .field-badge {
        width: auto;
        color: $text-muted;
    }
    .badge-explicit {
        color: $accent;
    }
    .badge-default, .badge-readonly {
        color: $text-muted;
    }
    .badge-automatic {
        color: $accent;
    }
    .aws-control {
        height: auto;
    }
    .mode-row, .aws-actions {
        height: auto;
    }
    .aws-select {
        width: 100%;
    }
    .aws-multiselect {
        height: auto;
        max-height: 6;
        border: round $panel;
    }
    .aws-status {
        height: auto;
        color: $text-muted;
    }
    .aws-status.status-loading {
        color: $accent;
    }
    .aws-status.status-results {
        color: $success;
    }
    .aws-status.status-empty {
        color: $warning;
    }
    .aws-status.status-failure {
        color: $error;
    }
    .verify-status {
        width: auto;
    }
    .verify-status.verify-verified {
        color: $success;
    }
    .verify-status.verify-failed {
        color: $error;
    }
    .verify-status.verify-none {
        color: $text-muted;
    }
    .field-input {
        margin: 0;
    }
    .field-help {
        color: $text-muted;
        height: auto;
    }
    .field-error {
        display: none;
        color: $error;
        height: auto;
    }
    .field-warning {
        display: none;
        color: $warning;
        height: auto;
    }
    .readonly-value {
        color: $text;
    }
    .kv-list {
        height: auto;
        max-height: 6;
        border: round $panel;
    }
    .kv-entry-row, .kv-button-row {
        height: auto;
    }
    .kv-key, .kv-value {
        width: 1fr;
    }
    #save-continue {
        margin-top: 1;
    }
    #field-help-dialog {
        width: 70;
        max-width: 90%;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #md-toolbar {
        height: auto;
        width: 100%;
    }
    .md-search {
        width: 1fr;
        margin: 0 1 0 0;
    }
    #md-toolbar Button {
        margin: 0 0 0 1;
    }
    #md-legend {
        height: auto;
        margin-bottom: 1;
    }
    #md-body {
        height: 1fr;
        width: 100%;
    }
    .md-list {
        width: 32;
        min-width: 20;
        height: 100%;
        border-right: solid $panel;
    }
    .md-detail {
        width: 1fr;
        height: 100%;
        padding: 0 1;
        overflow-y: auto;
    }
    #env-list Button {
        width: 100%;
        border: none;
        height: 1;
        margin-bottom: 0;
    }
    .env-active {
        color: $accent;
        text-style: bold;
    }
    .md-status {
        height: auto;
        color: $text-muted;
    }
    .md-empty {
        color: $text-muted;
    }
    #confirm-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-buttons {
        height: auto;
        margin-top: 1;
    }
    #confirm-buttons Button {
        margin: 0 1 0 0;
    }
    #impact-dialog {
        width: 70;
        max-width: 90%;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #impact-list {
        height: auto;
        max-height: 10;
        margin: 1 0;
        overflow-y: auto;
    }
    .impact-item {
        height: auto;
        color: $warning;
    }
    #impact-buttons {
        height: auto;
        margin-top: 1;
    }
    #impact-buttons Button {
        margin: 0 1 0 0;
    }
    #quit-dialog {
        width: 64;
        max-width: 90%;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #quit-buttons {
        height: auto;
        margin-top: 1;
    }
    #quit-buttons Button {
        margin: 0 1 0 0;
    }
    #merge-dialog, #conflict-dialog {
        width: 84;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #merge-patch, #conflict-list {
        height: auto;
        max-height: 16;
        margin: 1 0;
        overflow-y: auto;
    }
    #merge-buttons, #conflict-buttons {
        height: auto;
        margin-top: 1;
    }
    #merge-buttons Button, #conflict-buttons Button {
        margin: 0 1 0 0;
    }
    .conflict-path {
        text-style: bold;
        color: $accent;
        height: auto;
        margin-top: 1;
    }
    .conflict-baseline {
        color: $text-muted;
        height: auto;
    }
    .detail-form {
        height: auto;
    }
    .field-textarea {
        height: 6;
        border: round $panel;
    }
    .nested-collection {
        height: auto;
        border: round $panel;
        padding: 0 1;
        margin-bottom: 1;
    }
    .nested-title {
        text-style: bold;
        color: $accent;
    }
    .nested-toolbar {
        height: auto;
    }
    .nested-toolbar Button {
        margin: 0 1 0 0;
    }
    .nested-body {
        height: auto;
    }
    .nested-list {
        width: 28;
        min-width: 16;
        height: auto;
        max-height: 8;
        border-right: solid $panel;
    }
    .nested-detail {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    .nested-form {
        height: auto;
    }
    .nested-status {
        height: auto;
        color: $text-muted;
    }
    .cloudfront-panel {
        height: auto;
    }
    #review-problems, #review-risks {
        height: auto;
        margin-bottom: 1;
    }
    .review-alert-error {
        color: $error;
        height: auto;
    }
    .review-alert-warning {
        color: $warning;
        height: auto;
    }
    .risk-item {
        color: $warning;
        height: auto;
    }
    .review-problem, .topology-dangling {
        width: auto;
        height: auto;
        border: none;
        color: $error;
    }
    #review-tabs {
        height: 1fr;
    }
    #review-changes, #review-toml, #review-topology {
        height: 100%;
        width: 100%;
    }
    .review-change, .topology-node {
        height: auto;
    }
    .review-toml {
        height: auto;
    }
    .topology-edge {
        height: auto;
        color: $text-muted;
    }
    .topology-group {
        height: auto;
    }
    #risk-body, #review-save {
        height: auto;
    }
    #review-save {
        margin-top: 1;
    }
    """

    # Required bindings only. Bare n / p / q are deliberately absent: printable
    # keys must remain ordinary text input.
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+k", "command_palette", "Commands", show=True, priority=True),
        Binding("f1", "field_help", "Help", show=True, priority=True),
        Binding("escape", "close_overlay", "Back", show=True),
    ]

    def __init__(
        self,
        *,
        document: ProjectDocument,
        mode: str = "existing",
        discovery: AwsDiscovery | None = None,
        output_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._document = document
        # "existing" edits a document-preserving draft in place; "create" is a
        # first-time project whose files are generated only after Review confirms
        # creation.
        self._mode = mode
        # Where a first-time creation scaffolds its project. Defaults to the
        # document's own directory so the generated darth-infra.toml lands beside
        # the rest of the project.
        self._output_dir = output_dir or document.path.parent
        # AWS discovery/verification is injected. It defaults to an offline
        # adapter so the editor is fully usable — and saveable — without any AWS
        # credentials; production and tests supply a real or fake adapter.
        self._discovery: AwsDiscovery = discovery or OfflineAwsDiscovery()
        self.current_section: Section = Section.PROJECT
        self._section_widget: Any = None

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(
            f"Terminal too small.\nResize to at least {MIN_WIDTH}x{MIN_HEIGHT} "
            "to use the configuration editor.",
            id="too-small",
        )
        with Horizontal(id="editor-main"):
            with Vertical(id="nav-rail"):
                yield Static("Sections", classes="nav-heading")
                for section in SECTION_ORDER:
                    label = SECTION_LABELS[section]
                    available = section in IMPLEMENTED_SECTIONS
                    classes = "nav-item" if available else "nav-item nav-unavailable"
                    text = label if available else f"{label} (soon)"
                    yield Button(
                        text,
                        id=nav_button_id(section),
                        classes=classes,
                        compact=True,
                    )
            yield Container(id="content-host")
        yield Footer()

    async def on_mount(self) -> None:
        self.register_theme(CONTROL_ROOM_THEME)
        self.theme = THEME_NAME
        await self._show_section(Section.PROJECT)
        self._apply_min_size(self.size.width, self.size.height)

    # -- navigation --------------------------------------------------------

    async def _show_section(self, section: Section) -> None:
        self.current_section = section
        host = self.query_one("#content-host", Container)
        await host.remove_children()
        if section is Section.PROJECT:
            widget: Any = ProjectSection(self._document)
        elif section is Section.NETWORK:
            widget = NetworkSection(self._document, self._discovery)
        elif section is Section.SERVICES:
            widget = ServicesSection(self._document)
        elif section is Section.ROUTING:
            widget = RoutingSection(self._document, self._discovery)
        elif section is Section.DATABASE:
            widget = DatabaseSection(self._document)
        elif section is Section.STORAGE:
            widget = StorageSection(self._document)
        elif section is Section.SECRETS:
            widget = SecretsSection(self._document, self._discovery)
        elif section is Section.ENVIRONMENTS:
            widget = EnvironmentsSection(self._document)
        elif section is Section.REVIEW:
            widget = ReviewSection(self._document)
        else:
            widget = PlaceholderSection(section)
        self._section_widget = widget
        await host.mount(widget)
        self._refresh_nav_highlight()

    def _refresh_nav_highlight(self) -> None:
        for section in SECTION_ORDER:
            button = self.query_one(f"#{nav_button_id(section)}", Button)
            button.set_class(section == self.current_section, "nav-active")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        for section in SECTION_ORDER:
            if button_id == nav_button_id(section):
                event.stop()
                await self._show_section(section)
                return

    def on_project_section_save_continue_requested(
        self, event: ProjectSection.SaveContinueRequested
    ) -> None:
        event.stop()
        self._save_continue()

    def on_network_section_save_continue_requested(
        self, event: NetworkSection.SaveContinueRequested
    ) -> None:
        event.stop()
        self._save_continue()

    def on_routing_section_save_continue_requested(
        self, event: RoutingSection.SaveContinueRequested
    ) -> None:
        event.stop()
        self._save_continue()

    def on_routing_section_navigate_to_network_requested(
        self, event: RoutingSection.NavigateToNetworkRequested
    ) -> None:
        event.stop()
        self.run_worker(self._show_section(Section.NETWORK))

    def on_database_section_save_continue_requested(
        self, event: DatabaseSection.SaveContinueRequested
    ) -> None:
        event.stop()
        self._save_continue()

    def on_environments_section_save_continue_requested(
        self, event: EnvironmentsSection.SaveContinueRequested
    ) -> None:
        event.stop()
        self._save_continue()

    def on_review_section_save_requested(
        self, event: ReviewSection.SaveRequested
    ) -> None:
        event.stop()
        self._initiate_save()

    def on_review_section_navigate_to_control_requested(
        self, event: ReviewSection.NavigateToControlRequested
    ) -> None:
        event.stop()
        self.run_worker(
            self._navigate_to_control(event.section, event.path), exclusive=True
        )

    # -- responsive --------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        self._apply_min_size(event.size.width, event.size.height)

    def _apply_min_size(self, width: int, height: int) -> None:
        too_small = width < MIN_WIDTH or height < MIN_HEIGHT
        self.query_one("#too-small", Static).display = too_small
        self.query_one("#editor-main", Horizontal).display = not too_small

    # -- save orchestration ------------------------------------------------

    def action_save(self) -> None:
        """Ctrl+S: validate and save the draft from any section.

        The save is unified across every section: field errors surface adjacent
        to their controls, the complete model is validated (navigating to the
        first responsible control on failure), external disk changes are
        reconciled by three-way merge, and one confirmation covers every
        deployment-sensitive change. First-time creation is routed through Review.
        """
        self._initiate_save()

    def _save_continue(self) -> None:
        """Handle a section's Save & Continue action.

        For an existing project this is an ordinary save; for a first-time
        creation it validates the current section and advances the guided
        progression without writing files (creation is confirmed in Review).
        """
        section = self._section_widget
        if self._mode == "create":
            invalid = self._validate_section_fields(section)
            if invalid:
                self._report_field_errors(invalid)
                return
            self._suggest_next_section()
            return
        self._initiate_save(on_success=self._suggest_next_section)

    def _initiate_save(self, on_success: Callable[[], None] | None = None) -> None:
        """Central save entry point shared by Ctrl+S, Review, and Save & Continue."""
        # Never start a save while an overlay (a dialog) is open.
        if len(self.screen_stack) > 1:
            return

        if self._mode == "create":
            self._initiate_create(on_success)
            return

        section = self._section_widget
        if isinstance(section, ReviewSection):
            if self._report_problems(complete_validation_problems(self._document)):
                return
        elif hasattr(section, "validate_all"):
            invalid = self._validate_section_fields(section)
            if invalid:
                self._report_field_errors(invalid)
                return
            if self._report_problems(complete_validation_problems(self._document)):
                return
        else:
            self.notify("This section is not editable yet.", severity="warning")
            return

        # A merge or risk decision needs a dialog; otherwise write synchronously
        # so a plain edit-and-save stays a single, immediate operation.
        if self._disk_changed() or self._pending_risks():
            self.run_worker(self._save_with_dialogs(on_success), exclusive=True)
        elif self._write_and_report():
            self._after_successful_save(on_success)

    @staticmethod
    def _validate_section_fields(section: Any) -> list[Any]:
        if hasattr(section, "validate_all"):
            return list(section.validate_all())
        return []

    def _report_field_errors(self, invalid: list[Any]) -> None:
        first = invalid[0]
        inputs = first.query(Input)
        if inputs:
            inputs.first().focus()
        self.notify(
            f"Fix {len(invalid)} field error(s) before saving.", severity="error"
        )

    def _report_problems(self, problems: list[Any]) -> bool:
        """Report complete-model problems, navigating to the first; True if any."""
        if not problems:
            return False
        self.notify(
            f"Fix {len(problems)} validation problem(s) before saving.",
            severity="error",
        )
        self._navigate_to_problem(problems[0])
        return True

    def _navigate_to_problem(self, problem: Any) -> None:
        """Open the section owning ``problem`` unless it is already open.

        Re-rendering the section the operator is already on would only rebuild the
        same controls, so we leave them in place (their adjacent errors already
        show); a problem owned by a different section navigates there.
        """
        section = getattr(problem, "section", None)
        if section is None or section == self.current_section.value:
            return
        self.run_worker(
            self._navigate_to_control(section, getattr(problem, "path", None)),
            exclusive=True,
        )

    def _pending_risks(self) -> list[DeployRisk]:
        """Deployment-sensitive changes implied by the current unsaved diff."""
        try:
            changes = self._document.semantic_changes()
        except Exception:
            return []
        return deployment_sensitive_changes(changes)

    def _disk_changed(self) -> bool:
        """Whether the file on disk differs from the session baseline revision."""
        path = self._document.path
        if not path.exists():
            return False
        actual = hashlib.sha256(path.read_text().encode("utf-8")).hexdigest()
        return actual != self._document.revision

    async def _save_with_dialogs(
        self, on_success: Callable[[], None] | None
    ) -> None:
        """Reconcile external changes and confirm risk before writing."""
        merged = self._disk_changed()
        if merged and not await self._reconcile_disk():
            return

        risks = self._pending_risks()
        if risks and not await self.push_screen_wait(RiskConfirmScreen(risks)):
            self.notify("Save cancelled.", severity="warning")
            return

        if self._write_and_report():
            if merged:
                # The draft now embeds external edits; rebuild the section so its
                # controls reflect the merged document.
                await self._show_section(self.current_section)
            self._after_successful_save(on_success)

    async def _reconcile_disk(self) -> bool:
        """Three-way merge the draft with the changed disk file before writing.

        Disjoint changes merge automatically and are previewed before writing.
        True conflicts open a per-field resolver. Cancelling, an unresolved
        conflict, or a merged draft that fails validation all leave the draft and
        the disk file untouched. Returns True only when a clean, validated merge
        has been adopted and is ready to write.
        """
        result = self._document.merge_with_disk()
        if result.conflicts:
            choices = await self.push_screen_wait(
                ConflictResolverScreen(result.conflicts)
            )
            if choices is None:
                self.notify(
                    "Save cancelled; your draft and the file on disk are "
                    "unchanged.",
                    severity="warning",
                )
                return False
            result = self._document.merge_with_disk(resolutions=choices)

        if result.conflicts:
            self.notify(
                "Some conflicts are unresolved; not saved. Your draft is "
                "preserved.",
                severity="error",
            )
            return False
        if not result.ok:
            self.notify(
                "The merged configuration is invalid; not saved. Your draft is "
                "preserved.",
                severity="error",
            )
            return False

        patch = self._merged_patch(result)
        if not await self.push_screen_wait(
            MergePreviewScreen(patch, self._document.path.name)
        ):
            self.notify(
                "Save cancelled; your draft is preserved.", severity="warning"
            )
            return False

        self._document.adopt_merge(result)
        return True

    @staticmethod
    def _merged_patch(result: Any) -> str:
        import difflib

        merged = result.merged_text or ""
        diff = difflib.unified_diff(
            result.disk_text.splitlines(keepends=True),
            merged.splitlines(keepends=True),
            fromfile="darth-infra.toml (on disk)",
            tofile="darth-infra.toml (merged)",
        )
        return "".join(diff)

    def _write_and_report(self) -> bool:
        """Write the draft, reporting the path and semantic changed-field count."""
        try:
            count = len(self._document.semantic_changes())
        except Exception:
            count = 0
        try:
            self._document.save()
        except DocumentConflictError:
            self.notify(
                "darth-infra.toml changed on disk since it was last checked; not "
                "saved. Save again to merge the external change.",
                severity="error",
            )
            return False
        except DocumentValidationError as exc:
            self.notify(f"Cannot save: {exc.error}", severity="error")
            return False
        word = "field" if count == 1 else "fields"
        self.notify(
            f"Saved {self._document.path} ({count} {word} changed).",
            severity="information",
        )
        return True

    def _after_successful_save(
        self, on_success: Callable[[], None] | None
    ) -> None:
        """Refresh the current section after a save so stale state clears."""
        section = self._section_widget
        if isinstance(section, ReviewSection):
            section.refresh_views()
        elif hasattr(section, "after_save"):
            section.after_save()
        if on_success is not None:
            on_success()

    # -- first-time creation ----------------------------------------------

    def _initiate_create(self, on_success: Callable[[], None] | None) -> None:
        """First-time creation: route to Review, which owns the create confirm."""
        if isinstance(self._section_widget, ReviewSection):
            self.run_worker(self._create_flow(on_success), exclusive=True)
            return
        self.notify(
            "First-time creation is confirmed in Review before any files are "
            "written.",
            severity="information",
        )
        self.run_worker(self._show_section(Section.REVIEW), exclusive=True)

    async def _create_flow(self, on_success: Callable[[], None] | None) -> None:
        """Validate, confirm, and scaffold a first-time project's files."""
        if self._report_problems(complete_validation_problems(self._document)):
            return
        confirmed = await self.push_screen_wait(
            ConfirmScreen(
                "Create project?",
                "Generate the CloudFormation project and write its files under "
                f"{self._output_dir}? Nothing has been written yet.",
                confirm_label="Create project",
                confirm_variant="primary",
            )
        )
        if not confirmed:
            self.notify("Project creation cancelled.", severity="warning")
            return

        from ...config.loader import CONFIG_FILENAME
        from ...cli.version_floor import apply_current_cli_version_floor
        from ...scaffold.generator import generate_project

        config = self._document.config
        apply_current_cli_version_floor(config)
        generate_project(config, self._output_dir)
        self.notify(
            f"Created project at {self._output_dir}.", severity="information"
        )
        # The canonical file now exists; continue editing it document-preservingly.
        self._document = ProjectDocument.load(self._output_dir / CONFIG_FILENAME)
        self._mode = "existing"
        await self._show_section(Section.PROJECT)
        if on_success is not None:
            on_success()

    # -- quit --------------------------------------------------------------

    def action_quit(self) -> None:
        """Ctrl+Q: quit, offering to save or preserve unsaved work.

        A clean draft exits immediately. A dirty valid draft offers Save,
        Discard, or Cancel; a dirty invalid draft offers Return to fix or
        Discard. Invalid or unconvertible state is never written and never
        silently discarded — quitting always presents a choice.
        """
        if len(self.screen_stack) > 1:
            return
        self._commit_current_section()
        if not self._is_dirty():
            self.exit()
            return
        self.run_worker(self._quit_flow(), exclusive=True)

    async def _quit_flow(self) -> None:
        valid = self._document.validate().ok
        offer_save = valid and self._mode == "existing"
        choice = await self.push_screen_wait(
            QuitDecisionScreen(valid=valid, offer_save=offer_save)
        )
        if choice == "discard":
            self.exit()
        elif choice == "save":
            if await self._save_from_quit():
                self.exit()
        elif choice == "return":
            problems = complete_validation_problems(self._document)
            if problems:
                self._navigate_to_problem(problems[0])
        # "cancel": stay in the editor with the draft intact.

    async def _save_from_quit(self) -> bool:
        """Run the merge/risk-confirmed write for a valid draft during quit."""
        if self._disk_changed() and not await self._reconcile_disk():
            return False
        risks = self._pending_risks()
        if risks and not await self.push_screen_wait(RiskConfirmScreen(risks)):
            self.notify("Save cancelled.", severity="warning")
            return False
        return self._write_and_report()

    def _is_dirty(self) -> bool:
        try:
            return bool(self._document.toml_patch())
        except Exception:
            return True

    def _commit_current_section(self) -> None:
        """Flush any focused, uncommitted field edits into the draft."""
        section = self._section_widget
        if section is None:
            return
        commit_detail = getattr(section, "commit_detail", None)
        if callable(commit_detail):
            try:
                commit_detail()
            except Exception:
                pass
        try:
            for field in section.query(EditableField):
                field.commit()
        except Exception:
            pass

    # -- reversion ---------------------------------------------------------

    def action_revert_all(self) -> None:
        """Restore the entire draft to the last saved/loaded configuration.

        This also undoes cascading deletions, which are one draft transaction.
        """
        if not self._is_dirty():
            self.notify("No changes to revert.", severity="information")
            return
        self._document.revert_all()
        self.run_worker(self._reload_after_revert(), exclusive=True)
        self.notify(
            "Reverted all changes to the last saved configuration.",
            severity="information",
        )

    def action_revert_section(self) -> None:
        """Restore only the current section's fields to the session baseline."""
        targets = _SECTION_REVERT_TARGETS.get(self.current_section)
        if not targets:
            self.notify(
                "This section has nothing to revert on its own.",
                severity="information",
            )
            return
        for path in targets:
            self._document.revert_section(path)
        self.run_worker(self._reload_after_revert(), exclusive=True)
        self.notify(
            f"Reverted the {SECTION_LABELS[self.current_section]} section.",
            severity="information",
        )

    def action_reset_field(self) -> None:
        """Reset the focused field to its saved value and presence."""
        field = self._owning_field(self.focused)
        if field is None:
            self.notify("Focus a field to reset it.", severity="warning")
            return
        self._document.revert_field(field.field_path)
        self.run_worker(self._reload_after_revert(), exclusive=True)
        self.notify(
            f"Reset '{field.label}' to its saved value.", severity="information"
        )

    async def _reload_after_revert(self) -> None:
        """Rebuild the current section so its controls reflect a reversion."""
        await self._show_section(self.current_section)

    # -- command palette ---------------------------------------------------

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Save", "Validate and save the configuration", self.action_save
        )
        yield SystemCommand(
            "Reset field",
            "Reset the focused field to its saved value",
            self.action_reset_field,
        )
        yield SystemCommand(
            "Revert this section",
            "Discard this section's draft changes",
            self.action_revert_section,
        )
        yield SystemCommand(
            "Revert all changes",
            "Discard every draft change back to the last saved configuration",
            self.action_revert_all,
        )
        yield SystemCommand("Quit", "Quit the configuration editor", self.action_quit)

    async def _navigate_to_control(
        self, section_value: str, path: str | None
    ) -> None:
        """Open the owning section and, where practical, focus its control."""
        try:
            section = Section(section_value)
        except ValueError:
            return
        await self._show_section(section)
        if path:
            self._focus_field(path)

    def _focus_field(self, path: str) -> None:
        from .widgets import dom_slug

        slug = dom_slug(path)
        try:
            field = self.query_one(f"#field-{slug}")
        except Exception:
            return
        inputs = field.query(Input)
        if inputs:
            inputs.first().focus()
        else:
            try:
                field.focus()
            except Exception:
                pass

    def _suggest_next_section(self) -> None:
        index = SECTION_ORDER.index(self.current_section)
        if index + 1 < len(SECTION_ORDER):
            nxt = SECTION_ORDER[index + 1]
            self.run_worker(self._show_section(nxt))
            self.notify(
                f"Suggested next: {SECTION_LABELS[nxt]}. "
                "Any section remains directly reachable.",
                severity="information",
            )

    def action_field_help(self) -> None:
        field = self._owning_field(self.focused)
        if field is None:
            self.notify("Focus a field to see its help.", severity="warning")
            return
        self.push_screen(FieldHelpScreen(field.label, field.expanded_help()))

    def action_close_overlay(self) -> None:
        # Close a modal/overlay if one is open; never exit the base editor.
        if len(self.screen_stack) > 1:
            self.pop_screen()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _owning_field(widget: Any) -> EditableField | None:
        node = widget
        while node is not None:
            if isinstance(node, EditableField):
                return node
            node = node.parent
        return None


__all__ = ["ConfigEditorApp"]
