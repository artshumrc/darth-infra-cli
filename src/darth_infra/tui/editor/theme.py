"""Control-room visual language for the Guided editor.

The editor uses a restrained infrastructure-control-room palette expressed as
named semantic tokens rather than ad-hoc colors:

* slate surfaces for background/panels,
* cyan for focus and Automatic states,
* green for valid/verified states,
* amber for modified/unverified states,
* red for invalid/destructive states.

Color is never the only signal. Every semantic state pairs its color with text
or a symbol so the editor remains legible without color perception; the
``BADGE_*`` / ``*_SYMBOL`` constants below are those accompaniments.
"""

from __future__ import annotations

from textual.theme import Theme

THEME_NAME = "control-room"

CONTROL_ROOM_THEME = Theme(
    name=THEME_NAME,
    # Cyan: focus + Automatic states.
    primary="#38bdf8",
    secondary="#22d3ee",
    accent="#38bdf8",
    # Green valid/verified, amber modified/unverified, red invalid/destructive.
    success="#4ade80",
    warning="#fbbf24",
    error="#f87171",
    # Deep slate surfaces.
    foreground="#e2e8f0",
    background="#0f172a",
    surface="#1e293b",
    panel="#334155",
    dark=True,
)

# Text/symbol accompaniments for semantic states. These always appear next to
# the corresponding color so meaning survives without color perception.
BADGE_EXPLICIT = "◆ SET"          # ◆  an explicitly persisted value
BADGE_DEFAULT = "◇ DEFAULT"       # ◇  an omitted field showing its default
BADGE_READ_ONLY = "⊘ READ-ONLY"   # ⊘  CLI-maintained, not editable
BADGE_AUTOMATIC = "◈ AUTO"        # ◈  omitted; resolved automatically at deploy
BADGE_INHERITED = "◇ INHERITED"   # ◇  no environment override; inherits the base value
BADGE_OVERRIDE = "◆ OVERRIDE"     # ◆  an explicit per-environment override
ERROR_SYMBOL = "✗"                # ✗  precedes adjacent error text
VALID_SYMBOL = "✓"                # ✓  a validated value

# Verification status accompaniments (Not checked / Verified / Check failed).
VERIFY_NOT_CHECKED = "○ Not checked"
VERIFY_VERIFIED = "✓ Verified"
VERIFY_FAILED = "✗ Check failed"

__all__ = [
    "THEME_NAME",
    "CONTROL_ROOM_THEME",
    "BADGE_EXPLICIT",
    "BADGE_DEFAULT",
    "BADGE_READ_ONLY",
    "BADGE_AUTOMATIC",
    "BADGE_INHERITED",
    "BADGE_OVERRIDE",
    "ERROR_SYMBOL",
    "VALID_SYMBOL",
    "VERIFY_NOT_CHECKED",
    "VERIFY_VERIFIED",
    "VERIFY_FAILED",
]
