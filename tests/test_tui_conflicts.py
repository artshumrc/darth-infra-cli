"""External-change reconciliation for the Guided editor (ticket 15).

Textual Pilot flows for saving against a file that changed on disk after the
editor loaded it: disjoint edits merge automatically and preview before writing;
true same-field conflicts open a per-field resolver where the operator chooses a
side; cancelling or a merged draft that fails validation leaves both the draft
and the disk file untouched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, RadioButton

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.session import ConflictResolverScreen, MergePreviewScreen


BASE = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod", "staging"]

# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
"""


def _write(tmp_path: Path, text: str = BASE) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def test_disjoint_external_edit_merges_and_saves(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Draft edits the service CPU.
            app._document.set("services[0].cpu", 512)
            # Someone else edits an unrelated field on disk, with a comment.
            path.write_text(
                BASE.replace(
                    'name = "demo"',
                    '# renamed externally\nname = "demo-ext"',
                )
            )
            await pilot.press("ctrl+s")
            await pilot.pause()

            # The disjoint changes merged automatically and are previewed before
            # any write.
            assert isinstance(app.screen, MergePreviewScreen)
            await pilot.click("#merge-confirm")
            await pilot.pause()
            await pilot.pause()

    _run(scenario())

    reloaded = load_config(path)
    # Both edits are present.
    assert reloaded.services[0].cpu == 512
    assert reloaded.project_name == "demo-ext"
    # Neither document's unrelated formatting was lost.
    saved = path.read_text()
    assert "# The main web service" in saved
    assert "# renamed externally" in saved


def test_same_field_conflict_resolver_keeps_draft(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app._document.set("services[0].cpu", 512)  # draft
            path.write_text(BASE.replace("cpu = 256", "cpu = 999"))  # disk
            await pilot.press("ctrl+s")
            await pilot.pause()

            # A true conflict opens the resolver showing the field.
            assert isinstance(app.screen, ConflictResolverScreen)
            # Default choice keeps the draft; resolve and confirm the merge.
            await pilot.click("#conflict-resolve")
            await pilot.pause()
            assert isinstance(app.screen, MergePreviewScreen)
            await pilot.click("#merge-confirm")
            await pilot.pause()
            await pilot.pause()

    _run(scenario())
    assert load_config(path).services[0].cpu == 512


def test_same_field_conflict_resolver_keeps_disk(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app._document.set("services[0].cpu", 512)  # draft
            path.write_text(BASE.replace("cpu = 256", "cpu = 999"))  # disk
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert isinstance(app.screen, ConflictResolverScreen)
            # Choose "use theirs" (disk) for the single conflict.
            radios = app.screen.query(RadioButton)
            radios[1].value = True
            await pilot.pause()
            await pilot.click("#conflict-resolve")
            await pilot.pause()
            assert isinstance(app.screen, MergePreviewScreen)
            await pilot.click("#merge-confirm")
            await pilot.pause()
            await pilot.pause()

    _run(scenario())
    assert load_config(path).services[0].cpu == 999


def test_cancelling_conflict_leaves_draft_and_disk_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app._document.set("services[0].cpu", 512)  # draft
            path.write_text(BASE.replace("cpu = 256", "cpu = 999"))  # disk
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert isinstance(app.screen, ConflictResolverScreen)
            await pilot.click("#conflict-cancel")
            await pilot.pause()
            await pilot.pause()
            # The draft still holds the operator's value.
            assert app._document.value("services[0].cpu") == 512

    _run(scenario())
    # The file on disk is left exactly as the external editor wrote it.
    assert load_config(path).services[0].cpu == 999


def test_merged_validation_failure_preserves_draft_and_disk(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app._document.set("services[0].cpu", 512)  # disjoint draft edit
            # Disk drops the required prod environment: disjoint from the draft,
            # so no field conflict, but the merged document fails validation.
            path.write_text(
                BASE.replace('environments = ["prod", "staging"]', 'environments = ["staging"]')
            )
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.pause()

            # No merge is offered for an invalid result; the draft is preserved.
            assert not isinstance(app.screen, (MergePreviewScreen, ConflictResolverScreen))
            assert app._document.value("services[0].cpu") == 512

    _run(scenario())
    # The disk file is unchanged by the refused save.
    assert path.read_text().count('environments = ["staging"]') == 1
    assert "cpu = 512" not in path.read_text()
