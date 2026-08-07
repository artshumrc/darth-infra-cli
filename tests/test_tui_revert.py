"""Reversion controls for the Guided configuration editor (ticket 15).

Textual Pilot flows for the baseline-based reversion controls the shell exposes:
Reset field (focused field), Revert this section, and Revert all — including
that a cascading deletion (one draft transaction) is fully restored by a
whole-session revert. Each control is driven as the real app action a command
would run, then observed through the rebuilt controls and the document draft.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input

from darth_infra.config.document import ProjectDocument
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section


HAND = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod", "staging"]

[project.tags]
owner = "platform"

[[services]]
name = "web"
port = 8000
cpu = 256

[[services]]
name = "worker"
port = 9000
cpu = 128

[rds]
database_name = "app"
expose_to = ["web", "worker"]
"""


def _write(tmp_path: Path, text: str = HAND) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def test_reset_field_restores_focused_field_to_baseline(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            name = app.query_one("#input-project-name", Input)
            name.value = "changed"
            app.set_focus(name)
            await pilot.pause()
            assert app._document.value("project.name") == "changed"

            # Reset the focused field to its saved value.
            app.action_reset_field()
            await pilot.pause()
            await pilot.pause()
            assert app._document.value("project.name") == "demo"
            # The rebuilt control shows the restored value; other edits are safe.
            assert app.query_one("#input-project-name", Input).value == "demo"

    _run(scenario())


def test_reset_field_restores_omitted_presence(tmp_path: Path) -> None:
    # aws_region is omitted in the baseline here, so resetting a typed value must
    # restore omission, not write the default.
    text = HAND.replace('aws_region = "us-east-1"\n', "")
    path = _write(tmp_path, text)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            region = app.query_one("#input-project-aws-region", Input)
            region.value = "eu-west-1"
            app.set_focus(region)
            await pilot.pause()
            assert app._document.is_explicit("project.aws_region")

            app.action_reset_field()
            await pilot.pause()
            await pilot.pause()
            assert not app._document.is_explicit("project.aws_region")

    _run(scenario())


def test_revert_section_restores_only_that_section(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Edit a Project field and a Database field.
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            app._document.set("rds.database_name", "other")

            # Revert only the Project section.
            app.action_revert_section()
            await pilot.pause()
            await pilot.pause()

            # Project is restored; the Database edit is untouched.
            assert app._document.value("project.name") == "demo"
            assert app._document.value("rds.database_name") == "other"

    _run(scenario())


def test_revert_all_restores_the_whole_draft(tmp_path: Path) -> None:
    path = _write(tmp_path)
    original = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            app._document.set("services[0].cpu", 999)
            app._document.set("rds.database_name", "other")
            assert app._document.toml_patch() != ""

            app.action_revert_all()
            await pilot.pause()
            await pilot.pause()

            # Every change is gone and the draft matches the loaded document
            # exactly, comments and all.
            assert app._document.toml_patch() == ""
            assert app._document.to_toml() == original
            assert app.query_one("#input-project-name", Input).value == "demo"

    _run(scenario())


def test_revert_all_restores_a_cascading_deletion(tmp_path: Path) -> None:
    path = _write(tmp_path)
    original = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
            await pilot.pause()
            await pilot.pause()
            # Delete the referenced 'web' service and its cascade (its RDS
            # exposure) as one confirmed transaction.
            await pilot.click("#md-delete")
            await pilot.pause()
            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()

            # The cascade removed the service and cleaned up the reference.
            assert app._document.record_count("services") == 1
            assert app._document.value("rds.expose_to") == ["worker"]

            # A whole-session revert restores the entire cascade at once.
            app.action_revert_all()
            await pilot.pause()
            await pilot.pause()
            assert app._document.record_count("services") == 2
            assert app._document.value("rds.expose_to") == ["web", "worker"]
            assert app._document.to_toml() == original

    _run(scenario())
