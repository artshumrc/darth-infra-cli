"""The Review section: semantic changes, exact TOML, topology, and risk.

Review is an actionable representation of the current draft. It shows, for an
existing project:

* **Changes** — the semantic diff between the loaded/saved document and the
  draft, grouped by canonical editor section and labelled ``added``,
  ``removed``, ``changed``, or ``reset to default``. Unchanged fields are
  omitted. Environment-variable values appear as ordinary configuration.
* **TOML** — the exact document-preserving patch a save would write
  (:meth:`~darth_infra.config.document.ProjectDocument.toml_patch`), so the
  operator sees precisely what will change on disk.
* **Topology** — a compact view of the declared relationships among CloudFront,
  ALB routes, services, RDS, buckets, and secrets. It is explicitly configuration,
  not deployed AWS state; dangling relationships link to their owning editor.

Above the views, Review surfaces validation problems (which navigate to the
first responsible control) and deployment-sensitive warnings (what a future
deploy *may* do). Saving from Review requires one confirmation covering all
current deployment-sensitive changes. Actual secret values are never available
to Review; only the document's declared configuration is shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Static, TabbedContent, TabPane

from ..field_registry import Section
from ...config.deploy_risk import DeployRisk, deployment_sensitive_changes
from ...config.document import ABSENT, ChangeOperation, SemanticChange
from ...config.topology import (
    NODE_ALB,
    NODE_BUCKET,
    NODE_CLOUDFRONT,
    NODE_RDS,
    NODE_SECRET,
    NODE_SERVICE,
    Topology,
    TopologyEdge,
    derive_topology,
)
from .navigation import SECTION_LABELS

# Distinct, colour-independent labels for each semantic operation.
_OP_LABELS: dict[ChangeOperation, str] = {
    ChangeOperation.ADDED: "added",
    ChangeOperation.REMOVED: "removed",
    ChangeOperation.CHANGED: "changed",
    ChangeOperation.RESET_TO_DEFAULT: "reset to default",
}

_OP_GLYPHS: dict[ChangeOperation, str] = {
    ChangeOperation.ADDED: "+",
    ChangeOperation.REMOVED: "-",
    ChangeOperation.CHANGED: "~",
    ChangeOperation.RESET_TO_DEFAULT: "↺",
}

# Human labels for topology node kinds, in display order.
_NODE_KIND_LABELS: tuple[tuple[str, str], ...] = (
    (NODE_CLOUDFRONT, "CloudFront"),
    (NODE_ALB, "ALB routing"),
    (NODE_SERVICE, "Services"),
    (NODE_RDS, "Database"),
    (NODE_BUCKET, "Buckets"),
    (NODE_SECRET, "Secrets"),
)

# Above this many nodes+edges the topology groups start collapsed so Review
# remains usable for large projects.
TOPOLOGY_COLLAPSE_THRESHOLD = 12


@dataclass(frozen=True)
class ReviewProblem:
    """A validation problem shown before the diff/topology, with a target.

    ``section`` and ``path`` locate the responsible control so Review can
    navigate to it; either may be ``None`` when the problem cannot be attributed
    precisely.
    """

    message: str
    section: str | None = None
    path: str | None = None


def _section_for_semantic_path(path: str) -> Section:
    """Map a semantic diff path to the canonical editor section that owns it."""
    if path.startswith("project.environments"):
        return Section.ENVIRONMENTS
    if path.startswith("project."):
        rest = path[len("project.") :]
        head = rest.split(".", 1)[0].split("[", 1)[0]
        if head in {"vpc_name", "vpc_id", "private_subnet_ids", "public_subnet_ids"}:
            return Section.NETWORK
        return Section.PROJECT
    head = path.split(".", 1)[0].split("[", 1)[0]
    return {
        "services": Section.SERVICES,
        "service_discovery": Section.SERVICES,
        "alb": Section.ROUTING,
        "cloudfront": Section.ROUTING,
        "rds": Section.DATABASE,
        "s3_buckets": Section.STORAGE,
        "secrets": Section.SECRETS,
        "environments": Section.ENVIRONMENTS,
        "preview_environments": Section.ENVIRONMENTS,
    }.get(head, Section.PROJECT)


def _fmt(value: Any) -> str:
    """Render a diff value for display (env-var values included, verbatim)."""
    if value is ABSENT:
        return "(none)"
    if value is None:
        return "(none)"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _change_line(change: SemanticChange) -> str:
    glyph = _OP_GLYPHS[change.operation]
    label = _OP_LABELS[change.operation]
    if change.operation is ChangeOperation.ADDED:
        detail = _fmt(change.after)
    elif change.operation is ChangeOperation.REMOVED:
        detail = _fmt(change.before)
    elif change.operation is ChangeOperation.RESET_TO_DEFAULT:
        detail = f"{_fmt(change.before)} → default ({_fmt(change.after)})"
    else:
        detail = f"{_fmt(change.before)} → {_fmt(change.after)}"
    return f"{glyph} [{label}] {change.path}: {detail}"


class RiskConfirmScreen(ModalScreen[bool]):
    """One confirmation covering every deployment-sensitive change in a save.

    Lists what a future deploy *may* do and offers Save or Cancel. Returns
    ``True`` when the operator confirms the save.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, risks: list[DeployRisk]) -> None:
        super().__init__()
        self._risks = risks

    def compose(self) -> ComposeResult:
        count = len(self._risks)
        with Vertical(id="impact-dialog"):
            yield Static(
                "Deployment-sensitive changes", classes="section-title"
            )
            yield Static(
                f"{count} change(s) in this save may affect deployed "
                "infrastructure on the next deploy. This warns you now; only a "
                "deploy's CloudFormation changeset decides the exact effect.",
                id="risk-body",
            )
            with Vertical(id="impact-list"):
                for risk in self._risks:
                    yield Static(
                        f"• {risk.summary}", classes="impact-item", markup=False
                    )
            with Horizontal(id="impact-buttons"):
                yield Button(
                    "Save anyway", id="risk-confirm", variant="error"
                )
                yield Button("Cancel", id="risk-cancel", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "risk-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class ReviewSection(VerticalScroll):
    """Actionable Review of the current draft: changes, TOML, topology, risk."""

    class SaveRequested(Message):
        """Posted when the operator asks to save from Review."""

    class NavigateToControlRequested(Message):
        """Posted to open an owning editor (and focus a control where possible)."""

        def __init__(self, section: str, path: str | None) -> None:
            self.section = section
            self.path = path
            super().__init__()

    def __init__(self, document: Any) -> None:
        super().__init__(id="section-content", classes="section-content review-section")
        self.document = document
        # Owner target for each dangling-topology / problem navigation button,
        # keyed by the button id so a press resolves to a concrete control.
        self._nav_targets: dict[str, tuple[str, str | None]] = {}

    # -- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Review", classes="section-title")
        yield Static(
            "Your configuration draft — not deployed AWS state and not a "
            "CloudFormation plan.",
            classes="field-help",
        )
        yield Vertical(id="review-problems")
        yield Vertical(id="review-risks")
        with TabbedContent(id="review-tabs"):
            with TabPane("Changes", id="tab-changes"):
                yield VerticalScroll(id="review-changes")
            with TabPane("TOML", id="tab-toml"):
                yield VerticalScroll(id="review-toml")
            with TabPane("Topology", id="tab-topology"):
                yield VerticalScroll(id="review-topology")
        yield Button("Save", id="review-save", variant="primary")

    def on_mount(self) -> None:
        self.run_worker(self._render_all(), exclusive=True)

    # -- public API used by the shell --------------------------------------

    def refresh_views(self) -> None:
        """Recompute every view from the current draft (after save or revert)."""
        self.run_worker(self._render_all(), exclusive=True)

    def deployment_sensitive_changes(self) -> list[DeployRisk]:
        """The deployment-sensitive warnings implied by the current diff."""
        try:
            changes = self.document.semantic_changes()
        except Exception:
            return []
        return deployment_sensitive_changes(changes)

    def validation_problems(self) -> list[ReviewProblem]:
        """Complete-model validation problems, each pointing at a control.

        Dangling references (which also fail model validation) are reported with
        the precise owning control from the topology; any remaining model error
        is reported as a section-level problem attributed by keyword.
        """
        problems: list[ReviewProblem] = []
        topology = self._safe_topology()
        for edge in topology.dangling_edges:
            problems.append(
                ReviewProblem(
                    f"{edge.source} → {edge.target}: '{edge.target}' is not a "
                    "declared resource.",
                    section=edge.owner_section,
                    path=edge.owner_path,
                )
            )
        result = self.document.validate()
        if not result.ok and result.error and not problems:
            problems.append(self._attribute_error(result.error))
        return problems

    # -- rendering ---------------------------------------------------------

    async def _render_all(self) -> None:
        self._nav_targets = {}
        await self._render_problems()
        await self._render_risks()
        await self._render_changes()
        await self._render_toml()
        await self._render_topology()

    async def _render_problems(self) -> None:
        host = self.query_one("#review-problems", Vertical)
        await host.remove_children()
        problems = self.validation_problems()
        if not problems:
            host.display = False
            return
        host.display = True
        widgets: list[Any] = [
            Static(
                f"✗ {len(problems)} validation problem(s) — fix before saving:",
                classes="review-alert-error",
            )
        ]
        for index, problem in enumerate(problems):
            if problem.section is not None:
                button_id = f"review-problem-{index}"
                self._nav_targets[button_id] = (problem.section, problem.path)
                widgets.append(
                    Button(
                        f"→ {problem.message}",
                        id=button_id,
                        classes="review-problem",
                        compact=True,
                    )
                )
            else:
                widgets.append(
                    Static(
                        f"• {problem.message}",
                        classes="review-alert-error",
                        markup=False,
                    )
                )
        await host.mount(*widgets)

    async def _render_risks(self) -> None:
        host = self.query_one("#review-risks", Vertical)
        await host.remove_children()
        risks = self.deployment_sensitive_changes()
        if not risks:
            host.display = False
            return
        host.display = True
        widgets: list[Any] = [
            Static(
                f"⚠ {len(risks)} deployment-sensitive change(s). Saving needs "
                "confirmation; a future deploy may act on these:",
                classes="review-alert-warning",
            )
        ]
        for risk in risks:
            widgets.append(
                Static(f"• {risk.summary}", classes="risk-item", markup=False)
            )
        await host.mount(*widgets)

    async def _render_changes(self) -> None:
        host = self.query_one("#review-changes", VerticalScroll)
        await host.remove_children()
        try:
            changes = self.document.semantic_changes()
        except Exception as exc:  # pragma: no cover - defensive
            await host.mount(Static(f"Cannot compute changes: {exc}"))
            return
        if not changes:
            await host.mount(
                Static("No changes from the loaded configuration.", classes="md-empty")
            )
            return
        grouped: dict[Section, list[SemanticChange]] = {}
        for change in changes:
            grouped.setdefault(_section_for_semantic_path(change.path), []).append(
                change
            )
        widgets: list[Any] = []
        for section in Section:
            section_changes = grouped.get(section)
            if not section_changes:
                continue
            widgets.append(
                Static(SECTION_LABELS[section], classes="section-subtitle")
            )
            for change in section_changes:
                widgets.append(
                    Static(
                        _change_line(change),
                        classes="review-change",
                        markup=False,
                    )
                )
        await host.mount(*widgets)

    async def _render_toml(self) -> None:
        host = self.query_one("#review-toml", VerticalScroll)
        await host.remove_children()
        patch = self.document.toml_patch()
        if not patch:
            await host.mount(
                Static("No changes from the loaded configuration.", classes="md-empty")
            )
            return
        await host.mount(
            Static(
                patch, id="review-toml-body", classes="review-toml", markup=False
            )
        )

    async def _render_topology(self) -> None:
        host = self.query_one("#review-topology", VerticalScroll)
        await host.remove_children()
        topology = self._safe_topology()
        widgets: list[Any] = [
            Static(
                "Declared configuration relationships — not deployed AWS state.",
                classes="field-help",
            )
        ]
        if not topology.nodes:
            widgets.append(
                Static("No resources or relationships configured.", classes="md-empty")
            )
            await host.mount(*widgets)
            return
        collapse = topology.size > TOPOLOGY_COLLAPSE_THRESHOLD
        for kind, label in _NODE_KIND_LABELS:
            nodes = topology.nodes_of(kind)
            edges = [
                edge for edge in topology.edges if self._edge_belongs(edge, kind, topology)
            ]
            if not nodes and not edges:
                continue
            lines: list[Any] = []
            for node in nodes:
                lines.append(
                    Static(
                        f"▸ {node.name}", classes="topology-node", markup=False
                    )
                )
            for edge in edges:
                lines.append(self._edge_widget(edge))
            widgets.append(
                Collapsible(
                    *lines,
                    title=f"{label} ({len(nodes)})",
                    collapsed=collapse,
                    classes="topology-group",
                )
            )
        await host.mount(*widgets)

    @staticmethod
    def _edge_belongs(edge: TopologyEdge, kind: str, topology: Topology) -> bool:
        """Group an edge under the node kind of its source resource."""
        source_kinds = {node.name: node.kind for node in topology.nodes}
        origin = source_kinds.get(edge.source)
        if origin is not None:
            return origin == kind
        # A source that is not a node (should not happen) groups under services.
        return kind == NODE_SERVICE

    def _edge_widget(self, edge: TopologyEdge) -> Any:
        text = f"   {edge.source} → {edge.target} ({edge.label})"
        if not edge.dangling:
            return Static(text, classes="topology-edge", markup=False)
        button_id = f"review-dangling-{len(self._nav_targets)}"
        self._nav_targets[button_id] = (
            edge.owner_section or Section.SERVICES.value,
            edge.owner_path,
        )
        return Button(
            f"✗ {edge.source} → {edge.target} (dangling {edge.label}) — fix",
            id=button_id,
            classes="topology-dangling",
            compact=True,
        )

    # -- helpers -----------------------------------------------------------

    def _safe_topology(self) -> Topology:
        try:
            return derive_topology(self.document)
        except Exception:  # pragma: no cover - defensive
            return Topology()

    @staticmethod
    def _attribute_error(error: str) -> ReviewProblem:
        lowered = error.lower()
        table = (
            ("environments", Section.ENVIRONMENTS, "project.environments"),
            ("prod", Section.ENVIRONMENTS, "project.environments"),
            ("rds", Section.DATABASE, None),
            ("database", Section.DATABASE, None),
            ("secret", Section.SECRETS, None),
            ("bucket", Section.STORAGE, None),
            ("s3", Section.STORAGE, None),
            ("cloudfront", Section.ROUTING, None),
            ("alb", Section.ROUTING, None),
            ("listener", Section.ROUTING, None),
            ("service", Section.SERVICES, None),
            ("region", Section.PROJECT, "project.aws_region"),
            ("vpc", Section.NETWORK, "project.vpc_name"),
            ("subnet", Section.NETWORK, "project.private_subnet_ids"),
        )
        for keyword, section, path in table:
            if keyword in lowered:
                return ReviewProblem(error, section=section.value, path=path)
        return ReviewProblem(error, section=None, path=None)

    # -- events ------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "review-save":
            event.stop()
            self.post_message(self.SaveRequested())
            return
        if button_id in self._nav_targets:
            event.stop()
            section, path = self._nav_targets[button_id]
            self.post_message(self.NavigateToControlRequested(section, path))


__all__ = ["ReviewSection", "RiskConfirmScreen", "ReviewProblem"]
