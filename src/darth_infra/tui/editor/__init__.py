"""Guided configuration editor (Textual).

This package holds the document-preserving Guided editor introduced by the
``tui-configuration-editor`` epic. It is the single TUI architecture:
``darth-infra tui`` opens an existing project for document-preserving editing
and ``darth-infra init`` opens it in creation mode for first-run scaffolding.
"""

from __future__ import annotations

from .app import ConfigEditorApp

__all__ = ["ConfigEditorApp"]
