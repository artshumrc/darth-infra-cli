"""Project-section behavior for the Guided configuration editor (ticket 04).

These Textual Pilot tests drive the functional Project section through its
visible controls: editing identity/region/environments/tags, saving with
document preservation, read-only CLI metadata, Advanced-panel behavior, and
touched-field validation with live error clearing and contextual help.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Collapsible, Input, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.app import FieldHelpScreen
from darth_infra.tui.editor.review import RiskConfirmScreen

HAND_FORMATTED = """\
#:schema ./darth-infra.schema.json
#
# darth-infra config for the demo project.
# These comments and this ordering must survive a one-field edit.
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

# A document with no project tags, for the collapsed Advanced-panel case.
NO_TAGS = """\
[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
cpu = 256
"""


def _write(tmp_path: Path, text: str = HAND_FORMATTED) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


def test_edit_project_name_and_save_is_observed_by_load_config(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            name = app.query_one("#input-project-name", Input)
            name.value = "renamed-demo"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert load_config(path).project_name == "renamed-demo"

    _run(scenario())


def test_edit_region_and_environments_through_visible_controls(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-aws-region", Input).value = "eu-west-1"
            app.query_one("#input-project-environments", Input).value = "prod, dev"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            # Region and environment identity are deployment-sensitive, so the
            # unified save asks for one confirmation before writing (ticket 15).
            assert isinstance(app.screen, RiskConfirmScreen)
            await pilot.click("#risk-confirm")
            await pilot.pause()
            await pilot.pause()

            reloaded = load_config(path)
            assert reloaded.aws_region == "eu-west-1"
            assert reloaded.environments == ["prod", "dev"]

    _run(scenario())


def test_add_tag_through_advanced_panel_and_save(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#kvkey-project-tags", Input).value = "team"
            app.query_one("#kvval-project-tags", Input).value = "platform-eng"
            app.query_one("#kvadd-project-tags", Button).press()
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            reloaded = load_config(path)
            assert reloaded.tags == {"owner": "platform", "team": "platform-eng"}

    _run(scenario())


def test_save_preserves_comments_ordering_and_explicit_default(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)
    original = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "demo2"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    saved = path.read_text()
    # Comments and unrelated ordering survive.
    assert "# darth-infra config for the demo project." in saved
    assert "# The main web service" in saved
    assert "# Extra tags for every resource" in saved
    assert saved.index("aws_region") < saved.index("vpc_name")
    # The service's explicit value equal to its default is still present.
    assert "cpu = 256" in saved
    # Only the project name line changed.
    diff = [
        line
        for line in _unified(original, saved)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert diff == ['-name = "demo"', '+name = "demo2"']


def _unified(before: str, after: str) -> list[str]:
    import difflib

    return list(
        difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="")
    )


def test_cli_version_floor_is_visible_and_not_focusable(tmp_path: Path) -> None:
    text = HAND_FORMATTED.replace(
        'name = "demo"', 'name = "demo"\ncli_version_floor = "1.2.3"'
    )
    path = _write(tmp_path, text)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            field = app.query_one("#field-project-cli-version-floor")
            value = app.query_one("#value-project-cli-version-floor", Static)
            assert "1.2.3" in _rendered(value)
            # It renders no focusable control, so it cannot receive edit focus.
            assert len(field.query(Input)) == 0
            focusables = [w for w in field.walk_children() if w.focusable]
            assert focusables == []

    _run(scenario())


def test_advanced_panel_expands_for_configured_values(tmp_path: Path) -> None:
    path = _write(tmp_path)  # has project.tags configured

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            panel = app.query_one("#advanced-project", Collapsible)
            assert panel.collapsed is False
            assert "1 configured" in panel.title

    _run(scenario())


def test_advanced_panel_collapsed_with_count_when_unconfigured(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, NO_TAGS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            panel = app.query_one("#advanced-project", Collapsible)
            assert panel.collapsed is True
            # Configured count is reported on the collapsed heading.
            assert "0 configured" in panel.title

    _run(scenario())


def test_advanced_panel_expands_on_error(tmp_path: Path) -> None:
    path = _write(tmp_path, NO_TAGS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            panel = app.query_one("#advanced-project", Collapsible)
            assert panel.collapsed is True
            # An error in a contained advanced field forces the panel open.
            section = app._section_widget
            tags_field = app.query_one("#field-project-tags")
            tags_field.touched = True
            tags_field.show_error("example error")
            section._refresh_advanced()
            await pilot.pause()
            assert panel.collapsed is False

    _run(scenario())


def test_validation_appears_on_blur_and_clears_live_when_fixed(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            name = app.query_one("#input-project-name", Input)
            error = app.query_one("#error-project-name", Static)

            # Clearing the value while it stays focused does not yet show error.
            app.set_focus(name)
            await pilot.pause()
            name.value = ""
            await pilot.pause()
            assert error.display is False

            # Blurring the (now-touched) empty required field surfaces the error.
            app.set_focus(app.query_one("#input-project-aws-region", Input))
            await pilot.pause()
            assert error.display is True
            assert "required" in _rendered(error).lower()

            # Fixing it clears the error live, without another blur.
            name.value = "demo"
            await pilot.pause()
            assert error.display is False

    _run(scenario())


def test_environments_without_prod_reports_adjacent_error(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            envs = app.query_one("#input-project-environments", Input)
            app.set_focus(envs)
            await pilot.pause()
            envs.value = "staging, dev"
            await pilot.pause()
            app.set_focus(app.query_one("#input-project-name", Input))
            await pilot.pause()

            error = app.query_one("#error-project-environments", Static)
            assert error.display is True
            assert "prod" in _rendered(error).lower()

    _run(scenario())


def test_ctrl_s_blocks_save_on_invalid_and_writes_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path)
    original = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = ""
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            # Save was refused; the invalid required field now shows its error.
            assert app.query_one("#error-project-name", Static).display is True

    _run(scenario())

    assert path.read_text() == original


def test_contextual_help_and_f1_expanded_help(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Contextual help is visible inline for the field.
            help_line = app.query_one("#help-project-name", Static)
            assert "project name" in _rendered(help_line).lower()

            # F1 opens expanded help for the focused field, including its example.
            app.set_focus(app.query_one("#input-project-name", Input))
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(app.screen, FieldHelpScreen)
            body = app.screen.query_one("#field-help-body", Static)
            assert "my-webapp" in _rendered(body)

            # Escape closes the overlay and returns to the editor.
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FieldHelpScreen)

    _run(scenario())


def test_save_updates_explicit_badge(tmp_path: Path) -> None:
    path = _write(tmp_path, NO_TAGS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # aws_region is explicit in NO_TAGS, so its badge reads SET.
            badge = app.query_one("#badge-project-aws-region", Static)
            assert "SET" in _rendered(badge)

    _run(scenario())
