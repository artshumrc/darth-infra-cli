"""Guided configuration editor (Textual).

This package holds the new document-preserving Guided editor introduced by the
``tui-configuration-editor`` epic. It is kept internal until the atomic CLI
cutover (ticket 16); ``darth-infra tui`` continues to launch the legacy wizard
in :mod:`darth_infra.tui.app` until then.
"""

from __future__ import annotations

from .app import ConfigEditorApp

__all__ = ["ConfigEditorApp"]
