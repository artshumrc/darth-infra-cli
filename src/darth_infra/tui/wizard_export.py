"""Wizard draft import/export helpers."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class WizardExport:
    version: int
    completed: bool
    last_screen: str
    state: dict[str, Any]


def default_wizard_state() -> dict[str, Any]:
    """Default mutable wizard state shared across TUI screens."""
    return {
        "project_name": "",
        "vpc_name": "artshumrc-prod-standard",
        "aws_region": "us-east-1",
        "environments": ["prod"],
        "services": [],
        "rds": None,
        "s3_buckets": [],
        "alb_mode": "shared",
        "shared_alb_name": "",
        "shared_listener_arn": None,
        "shared_alb_security_group_id": None,
        "certificate_arn": None,
        "alb_domain": None,
        "default_target_service": None,
        "default_listener_priority": None,
        "alb_path_rules": [],
        "secrets": [],
        "_wizard_draft": {},
        "_wizard_last_screen": "welcome",
    }


def merge_seed_state(seed: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a seed export state into defaults (best-effort, non-strict)."""
    state = default_wizard_state()
    if not isinstance(seed, dict):
        return state

    for key in state:
        if key in seed:
            state[key] = seed[key]

    # Preserve extra keys too, to avoid dropping future draft fields.
    for key, value in seed.items():
        if key not in state:
            state[key] = value

    if not isinstance(state.get("_wizard_draft"), dict):
        state["_wizard_draft"] = {}
    else:
        # Service draft data is highly contextual to the last focused item and
        # can corrupt resumed edits when real services already exist.
        if state.get("services"):
            state["_wizard_draft"].pop("services", None)
    if not isinstance(state.get("_wizard_last_screen"), str):
        state["_wizard_last_screen"] = "welcome"

    return state


def load_wizard_export(path: Path) -> WizardExport | None:
    """Load wizard export JSON if it exists and is valid enough."""
    if not path.is_file():
        return None

    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        return None

    return WizardExport(
        version=int(raw.get("version", 1)),
        completed=bool(raw.get("completed", False)),
        last_screen=str(raw.get("last_screen", "welcome")),
        state=raw.get("state", {}) if isinstance(raw.get("state"), dict) else {},
    )


def save_wizard_export(
    path: Path,
    *,
    state: dict[str, Any],
    completed: bool,
    last_screen: str,
) -> None:
    """Save wizard export JSON for resume/debugging."""
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed": completed,
        "last_screen": last_screen,
        # Make a deep copy to prevent accidental later mutations.
        "state": deepcopy(state),
    }

    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
