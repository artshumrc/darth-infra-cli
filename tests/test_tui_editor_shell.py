"""Shell-level behavior for the Guided configuration editor (ticket 04).

These are the repository's first Textual Pilot tests: they launch the real
application with :meth:`textual.app.App.run_test` against a temporary project
document and drive it through the same controls a user would. They cover the
non-linear navigation shell, required key bindings, responsive layout, and the
guarantee that the legacy CLI still launches the legacy wizard until cutover.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Collapsible, Input, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import (
    IMPLEMENTED_SECTIONS,
    SECTION_ORDER,
    nav_button_id,
)
from darth_infra.tui.field_registry import Section

HAND_FORMATTED = """\
#:schema ./darth-infra.schema.json
#
# darth-infra config for the demo project.
# These comments and this ordering must survive edits.
#

[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod", "staging"]

# Extra tags for every resource
[project.tags]
owner = "platform"

# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
memory_mib = 512
desired_count = 2
"""


def _write_config(tmp_path: Path, text: str = HAND_FORMATTED) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def test_pilot_launches_shell_with_existing_document(tmp_path: Path) -> None:
    path = _write_config(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # The Project section is shown and reflects the loaded document.
            assert app.query_one("#input-project-name", Input).value == "demo"
            # All nine canonical destinations exist in the nav rail.
            for section in SECTION_ORDER:
                assert app.query_one(f"#{nav_button_id(section)}", Button)

    _run(scenario())


def test_navigation_is_non_linear_and_marks_unavailable_sections(
    tmp_path: Path,
) -> None:
    path = _write_config(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Jump straight to a late destination without visiting the ones
            # before it: navigation is not a linear wizard.
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            assert app.current_section is Section.REVIEW
            message = app.query_one(".placeholder-message", Static)
            assert "not available yet" in str(message.render())

            # And back to Project directly.
            await pilot.click(f"#{nav_button_id(Section.PROJECT)}")
            await pilot.pause()
            assert app.current_section is Section.PROJECT
            assert app.query_one("#input-project-name", Input)

    _run(scenario())


def test_project_and_services_are_implemented() -> None:
    # Project (ticket 04), Network (ticket 05), Services (ticket 06), Routing
    # (ticket 08), and Database (ticket 10) have functional editors; the rest
    # remain reachable placeholders until their own slices.
    assert {
        Section.PROJECT,
        Section.NETWORK,
        Section.SERVICES,
        Section.ROUTING,
        Section.DATABASE,
        Section.STORAGE,
        Section.SECRETS,
    } <= IMPLEMENTED_SECTIONS
    # All nine destinations are represented.
    assert len(SECTION_ORDER) == 9


def test_required_bindings_present_and_no_printable_globals() -> None:
    keys = {b.key for b in ConfigEditorApp.BINDINGS}
    assert {"ctrl+s", "ctrl+k", "f1", "escape"} <= keys
    # Bare n / p / q are never global bindings in the new editor.
    assert "n" not in keys
    assert "p" not in keys
    assert "q" not in keys


def test_printable_keys_are_ordinary_input_text(tmp_path: Path) -> None:
    path = _write_config(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            name = app.query_one("#input-project-name", Input)
            name.value = ""
            app.set_focus(name)
            await pilot.pause()
            await pilot.press("n", "p", "q", "x")
            await pilot.pause()
            # The keystrokes landed as text; none acted as a global shortcut.
            assert name.value == "npqx"
            assert app.is_running

    _run(scenario())


def test_ctrl_k_opens_command_palette(tmp_path: Path) -> None:
    path = _write_config(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            depth = len(app.screen_stack)
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert len(app.screen_stack) > depth

    _run(scenario())


def test_responsive_minimum_size_message(tmp_path: Path) -> None:
    path = _write_config(tmp_path)

    async def scenario(size: tuple[int, int], too_small: bool) -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            overlay = app.query_one("#too-small", Static)
            main = app.query_one("#editor-main")
            assert overlay.display is too_small
            assert main.display is (not too_small)
            if not too_small:
                # Required Project actions remain reachable.
                assert app.query_one("#save-continue", Button).display is True
                assert app.query_one("#input-project-name", Input).display is True

    _run(scenario((120, 35), False))
    _run(scenario((80, 24), False))
    _run(scenario((79, 23), True))


def test_legacy_cli_still_launches_legacy_app() -> None:
    # The atomic cutover (ticket 16) has not happened: the legacy wizard app and
    # its CLI wiring remain in place and importable.
    from darth_infra.tui.app import DarthEcsInitApp
    from darth_infra.cli import init_cmd as init_module

    assert DarthEcsInitApp is not None
    source = Path(init_module.__file__).read_text()
    assert "DarthEcsInitApp" in source
    assert "ConfigEditorApp" not in source
