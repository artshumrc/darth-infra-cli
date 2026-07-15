"""Save and quit workflows for the Guided configuration editor (ticket 15).

Textual Pilot flows for the unified save orchestration and the quit prompt:
saving from any section, the path/count save report, first-time creation gated
behind Review, and the Save/Discard/Cancel and Return/Discard quit choices —
including the guarantee that invalid state is never written and never silently
discarded, and that no autosave/recovery file is ever created.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.collection import ConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.editor.review import RiskConfirmScreen
from darth_infra.tui.editor.session import QuitDecisionScreen
from darth_infra.tui.field_registry import Section


HAND = """\
#:schema ./darth-infra.schema.json
#
# darth-infra config for the demo project.
# These comments must survive edits.
#

[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod", "staging"]

[project.tags]
owner = "platform"

# The main web service
[[services]]
name = "web"
port = 8000
cpu = 256
health_check_path = "/health"
"""


def _write(tmp_path: Path, text: str = HAND) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _record_notifications(app) -> list[str]:
    messages: list[str] = []
    original = app.notify

    def recorder(message, **kwargs):
        messages.append(str(message))
        return original(message, **kwargs)

    app.notify = recorder  # type: ignore[method-assign]
    return messages


async def _ctrl_s(app, pilot) -> None:
    await pilot.press("ctrl+s")
    await pilot.pause()
    if isinstance(app.screen, RiskConfirmScreen):
        await pilot.click("#risk-confirm")
        await pilot.pause()
    await pilot.pause()


# -- saving from any section ------------------------------------------------


def test_existing_project_saves_from_project_section(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await _ctrl_s(app, pilot)
            assert load_config(path).project_name == "renamed"

    _run(scenario())


def test_existing_project_saves_from_non_project_section(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Navigate straight to Services and save an ordinary field without
            # ever visiting Review.
            await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
            await pilot.pause()
            await pilot.pause()
            app.query_one("#input-services-0-cpu", Input).value = "1024"
            await pilot.pause()
            await _ctrl_s(app, pilot)
            assert app.current_section is Section.SERVICES
            assert load_config(path).services[0].cpu == 1024

    _run(scenario())


def test_successful_save_reports_path_and_field_count(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            messages = _record_notifications(app)
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await _ctrl_s(app, pilot)
            report = [m for m in messages if "Saved" in m]
            assert report, messages
            assert str(path) in report[-1]
            assert "1 field changed" in report[-1]

    _run(scenario())


def test_save_clears_diff_and_risk(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # A deployment-sensitive change: region identity.
            app.query_one("#input-project-aws-region", Input).value = "eu-west-1"
            await pilot.pause()
            assert app._document.semantic_changes()
            await _ctrl_s(app, pilot)

            # After the save the diff is gone and the risk warning has cleared.
            assert app._document.toml_patch() == ""
            assert app._document.semantic_changes() == []
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#review-risks").display is False

    _run(scenario())


def test_no_autosave_or_recovery_file_is_created(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            # Editing without saving must not persist anything to disk.
            assert [p.name for p in tmp_path.iterdir()] == ["darth-infra.toml"]
            await _ctrl_s(app, pilot)
            # After a save, only the config file remains — no temp/recovery file.
            assert sorted(p.name for p in tmp_path.iterdir()) == ["darth-infra.toml"]

    _run(scenario())


# -- first-time creation ----------------------------------------------------


CREATE = """\
[project]
name = "brandnew"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
cpu = 256
"""


def test_first_time_creation_defers_to_review_then_scaffolds(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    out.mkdir()
    toml_path = out / "darth-infra.toml"

    async def scenario() -> None:
        # A create-mode document whose file does not exist yet.
        app = ConfigEditorApp(document=ProjectDocument(toml_path, CREATE), mode="create")
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Ctrl+S from Project must not write files; it routes to Review.
            await _ctrl_s(app, pilot)
            assert not toml_path.exists()
            assert app.current_section is Section.REVIEW

            # Saving from Review asks for an explicit creation confirmation.
            await pilot.click("#review-save")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-yes")
            await pilot.pause()
            await pilot.pause()

    _run(scenario())

    # Canonical project output was produced by the existing scaffold.
    assert toml_path.is_file()
    assert (out / "templates" / "generated" / "root.yaml").is_file()
    reloaded = load_config(toml_path)
    assert reloaded.project_name == "brandnew"


def test_first_time_creation_cancel_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    out.mkdir()
    toml_path = out / "darth-infra.toml"

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument(toml_path, CREATE), mode="create")
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            await pilot.click("#review-save")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-no")
            await pilot.pause()

    _run(scenario())

    assert not toml_path.exists()
    assert not (out / "templates").exists()


# -- quit -------------------------------------------------------------------


def test_quit_with_no_changes_exits_immediately(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running

    _run(scenario())


def test_quit_valid_dirty_offers_save_discard_cancel(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitDecisionScreen)
            # All three choices are offered for a valid dirty draft.
            assert app.screen.query_one("#quit-save")
            assert app.screen.query_one("#quit-discard")
            assert app.screen.query_one("#quit-cancel")

            # Cancel keeps the editor open with the draft intact.
            await pilot.click("#quit-cancel")
            await pilot.pause()
            assert app.is_running
            assert app.query_one("#input-project-name", Input).value == "renamed"

    _run(scenario())


def test_quit_save_writes_then_exits(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            await pilot.click("#quit-save")
            await pilot.pause()
            await pilot.pause()
            assert not app.is_running

    _run(scenario())
    assert load_config(path).project_name == "renamed"


def test_quit_discard_exits_without_writing(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            await pilot.click("#quit-discard")
            await pilot.pause()
            assert not app.is_running

    _run(scenario())
    # The draft was discarded; the file on disk is unchanged.
    assert load_config(path).project_name == "demo"


def test_quit_invalid_dirty_offers_return_or_discard_never_save(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
            await pilot.pause()
            await pilot.pause()
            # A second service with a duplicate name fails model validation, so
            # the draft is dirty and invalid.
            app._document.add_record("services", {"name": "web", "port": 9000})
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert isinstance(app.screen, QuitDecisionScreen)
            # No Save is offered for an invalid draft, and the app is still up:
            # invalid state is never written and never silently discarded.
            assert app.screen.query_one("#quit-return")
            assert app.screen.query_one("#quit-discard")
            assert not app.screen.query("#quit-save")
            assert app.is_running

            # Return to fix keeps the editor open on the offending section with
            # the draft intact — never a silent exit.
            await pilot.click("#quit-return")
            await pilot.pause()
            await pilot.pause()
            assert app.is_running
            assert app.current_section is Section.SERVICES
            assert app._document.record_count("services") == 2

    _run(scenario())
    # Nothing was written by the invalid-quit attempt.
    assert len(load_config(path).services) == 1


def test_quit_invalid_dirty_discard_exits(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-environments", Input).value = "staging"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()
            await pilot.click("#quit-discard")
            await pilot.pause()
            assert not app.is_running

    _run(scenario())
    assert load_config(path).environments == ["prod", "staging"]
