"""Canonical section navigation for the Guided editor.

Nine destinations exist, in this fixed order: Project, Network, Services,
Routing, Database, Storage, Secrets, Environments, and Review. Navigation is
*non-linear* — any destination can be selected directly — so this module only
defines the destinations and their display labels, not an ordering constraint.

All nine destinations are functional editors.
"""

from __future__ import annotations

from ..field_registry import Section

# The nine canonical destinations, in canonical display order.
SECTION_ORDER: tuple[Section, ...] = (
    Section.PROJECT,
    Section.NETWORK,
    Section.SERVICES,
    Section.ROUTING,
    Section.DATABASE,
    Section.STORAGE,
    Section.SECRETS,
    Section.ENVIRONMENTS,
    Section.REVIEW,
)

SECTION_LABELS: dict[Section, str] = {
    Section.PROJECT: "Project",
    Section.NETWORK: "Network",
    Section.SERVICES: "Services",
    Section.ROUTING: "Routing",
    Section.DATABASE: "Database",
    Section.STORAGE: "Storage",
    Section.SECRETS: "Secrets",
    Section.ENVIRONMENTS: "Environments",
    Section.REVIEW: "Review",
}

# Sections with a functional editor. At cutover this is every canonical
# destination; the set is retained so navigation can still distinguish an
# available editor from an unavailable one if that distinction ever returns.
IMPLEMENTED_SECTIONS: frozenset[Section] = frozenset(
    {
        Section.PROJECT,
        Section.NETWORK,
        Section.SERVICES,
        Section.ROUTING,
        Section.DATABASE,
        Section.STORAGE,
        Section.SECRETS,
        Section.ENVIRONMENTS,
        Section.REVIEW,
    }
)


def nav_button_id(section: Section) -> str:
    """Stable DOM id for a section's navigation button."""
    return f"nav-{section.value}"


__all__ = [
    "SECTION_ORDER",
    "SECTION_LABELS",
    "IMPLEMENTED_SECTIONS",
    "nav_button_id",
]
