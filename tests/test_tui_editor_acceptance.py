"""Release-gate acceptance suite for the atomic Guided-editor cutover (ticket 16).

These Textual Pilot scenarios exercise the shipped editor as one whole through
the same controls a user operates: every canonical section is reachable and
functional, a comprehensive multi-resource project survives a no-op editor save
unchanged, the required keyboard commands work, and the responsive contract
(usable at 120x35 and 80x24, minimum-size message below that) holds. Per-section
behavior is covered in depth by the ticket 04-15 suites; this file is the
integration gate that proves they compose into a single, complete editor.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import (
    IMPLEMENTED_SECTIONS,
    SECTION_ORDER,
    nav_button_id,
)
from darth_infra.tui.editor.review import RiskConfirmScreen
from darth_infra.tui.field_registry import (
    Section,
    enumerate_schema_paths,
    load_schema,
    uncovered_editable_paths,
)

# A comprehensive project touching every editable resource family: services,
# storage, secrets, database, shared ALB routing with a path rule, CloudFront,
# a non-prod environment with an override, and preview environments.
COMPREHENSIVE = """\
#:schema ./darth-infra.schema.json
# Hand-authored comment that must survive a no-op save.
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
memory_mib = 512

[services.environment_variables]
LOG_LEVEL = "info"

[[services]]
name = "worker"
cpu = 256

[[s3_buckets]]
name = "media"

[[s3_buckets.connections]]
service = "web"
env_key = "MEDIA_BUCKET"

[[secrets]]
name = "API_KEY"
source = "generate"

[rds]
database_name = "app"
expose_to = ["web"]

[alb]
mode = "shared"
domain = "example.com"
default_target_service = "web"

[[alb.path_rules]]
name = "api"
path_pattern = "/api/*"
target_service = "web"

[cloudfront]
enabled = true

[[cloudfront.cached_behaviors]]
name = "static"
path_pattern = "/static/*"

[environments.staging]

[environments.staging.tags]
tier = "staging"

[preview_environments]
enabled = true
base_environment = "prod"
name_pattern = "pr-{number}"
domain_template = "pr-{number}.example.com"
"""

DEDICATED = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[alb]
mode = "dedicated"
certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"
domain = "demo.example.com"
default_target_service = "web"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


async def _activate(app, pilot, widget_id: str) -> None:
    """Activate a control by keyboard only: focus it and press Enter."""
    app.set_focus(app.query_one(widget_id, Button))
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


# -- completeness -----------------------------------------------------------


def test_every_section_is_a_functional_editor() -> None:
    # No canonical destination is a placeholder at cutover.
    assert set(SECTION_ORDER) == IMPLEMENTED_SECTIONS
    assert len(SECTION_ORDER) == 9


def test_schema_coverage_has_no_missing_editable_fields() -> None:
    schema = load_schema()
    assert uncovered_editable_paths(schema) == set()
    # Only the accepted CLI-maintained read-only exemption exists.
    assert enumerate_schema_paths(schema).read_only == {"project.cli_version_floor"}


def test_all_nine_sections_reachable_keyboard_only_at_120x35(tmp_path: Path) -> None:
    path = _write(tmp_path, COMPREHENSIVE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            for section in SECTION_ORDER:
                await _activate(app, pilot, f"#{nav_button_id(section)}")
                assert app.current_section is section
                # A functional editor renders real content, never a placeholder.
                assert not app.query(".placeholder-message")

    _run(scenario())


def test_all_nine_sections_reachable_at_80x24(tmp_path: Path) -> None:
    path = _write(tmp_path, COMPREHENSIVE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # The editor is usable (not the minimum-size message) at 80x24.
            assert app.query_one("#too-small", Static).display is False
            assert app.query_one("#editor-main").display is True
            for section in SECTION_ORDER:
                await pilot.click(f"#{nav_button_id(section)}")
                await pilot.pause()
                assert app.current_section is section
                assert not app.query(".placeholder-message")

    _run(scenario())


# -- responsive -------------------------------------------------------------


def test_minimum_size_message_below_80x24(tmp_path: Path) -> None:
    path = _write(tmp_path, COMPREHENSIVE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(79, 23)) as pilot:
            await pilot.pause()
            assert app.query_one("#too-small", Static).display is True
            assert app.query_one("#editor-main").display is False

    _run(scenario())


# -- keyboard completeness --------------------------------------------------


def test_required_keyboard_commands_work(tmp_path: Path) -> None:
    path = _write(tmp_path, COMPREHENSIVE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            depth = len(app.screen_stack)

            # Ctrl+K opens the command palette; Escape closes it.
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert len(app.screen_stack) > depth
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == depth

            # F1 opens contextual help for the focused field; Escape closes it.
            app.set_focus(app.query_one("#input-project-name"))
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert len(app.screen_stack) > depth
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == depth

    _run(scenario())


# -- no-op save survival ----------------------------------------------------


async def _noop_save(app, pilot) -> None:
    await pilot.press("ctrl+s")
    await pilot.pause()
    if isinstance(app.screen, RiskConfirmScreen):
        await pilot.click("#risk-confirm")
        await pilot.pause()
    await pilot.pause()


def test_comprehensive_fixture_survives_noop_editor_save(tmp_path: Path) -> None:
    path = _write(tmp_path, COMPREHENSIVE)
    before = path.read_text()
    before_config = load_config(path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _noop_save(app, pilot)

    _run(scenario())

    # Document-preserving save of an unedited draft rewrites nothing.
    assert path.read_text() == before
    assert load_config(path) == before_config


def test_dedicated_alb_fixture_survives_noop_editor_save(tmp_path: Path) -> None:
    path = _write(tmp_path, DEDICATED)
    before = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Visit Routing, then save without edits: dedicated mode must not be
            # converted to shared.
            await pilot.click(f"#{nav_button_id(Section.ROUTING)}")
            await pilot.pause()
            await _noop_save(app, pilot)

    _run(scenario())

    assert path.read_text() == before
    cfg = load_config(path)
    assert cfg.alb.mode.value == "dedicated"
    assert cfg.alb.certificate_arn == (
        "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"
    )
