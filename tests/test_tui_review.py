"""Review section: semantic Changes and exact TOML views (ticket 14).

Drives the Review section through Textual Pilot: the section-grouped semantic
change list with distinct add/remove/change/reset-to-default labels, the exact
document-preserving TOML patch, omission of unchanged fields, and validation
problems that appear before the diff and navigate to the first responsible
control.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section


CONFIG = """\
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
health_check_path = "/health"

[[secrets]]
name = "API_KEY"
source = "generate"

[rds]
database_name = "app"
expose_to = ["web"]
"""


def _write(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


async def _goto_review(app, pilot) -> None:
    await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
    await pilot.pause()
    await pilot.pause()


def _changes_text(app) -> str:
    return "\n".join(
        str(s.render()) for s in app.query_one("#review-changes").query(Static)
    )


def _toml_text(app) -> str:
    return "\n".join(
        str(s.render()) for s in app.query_one("#review-toml").query(Static)
    )


def test_no_changes_shows_empty_state(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_review(app, pilot)
            assert "No changes" in _changes_text(app)
            assert "No changes" in _toml_text(app)

    _run(scenario())


def test_changes_grouped_by_section_with_distinct_labels(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            doc = app._document
            # A representative edit in several canonical sections.
            doc.set("project.name", "demo2")  # changed (Project)
            doc.set("project.tags.team", "platform")  # added (Project)
            doc.reset("project.tags.owner")  # removed (Project map entry)
            doc.set("rds.expose_to", [])  # changed (Database)
            doc.reset("services[0].health_check_path")  # reset to default (Services)
            await _goto_review(app, pilot)

            text = _changes_text(app)
            # Grouped under canonical section headers.
            assert "Project" in text
            assert "Database" in text
            assert "Services" in text
            # Distinct visible labels for each operation kind.
            assert "[changed]" in text
            assert "[added]" in text
            assert "[removed]" in text
            assert "[reset to default]" in text

    _run(scenario())


FULL = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000
cpu = 256

[[s3_buckets]]
name = "media"

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
"""


def test_changes_cover_representative_edits_in_every_section(tmp_path: Path) -> None:
    path = _write(tmp_path, FULL)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            doc = app._document
            doc.set("project.name", "demo2")  # Project
            doc.set("project.vpc_name", "vpc-y")  # Network
            doc.set("services[0].cpu", 512)  # Services
            doc.set("alb.domain", "new.example.com")  # Routing
            doc.set("rds.database_name", "app2")  # Database
            doc.set("s3_buckets[0].public_read", True)  # Storage
            doc.set("secrets[0].length", 40)  # Secrets
            doc.set("project.environments", ["prod", "staging", "dev"])  # Environments
            await _goto_review(app, pilot)

            text = _changes_text(app)
            for label in (
                "Project",
                "Network",
                "Services",
                "Routing",
                "Database",
                "Storage",
                "Secrets",
                "Environments",
            ):
                assert label in text, f"{label} section missing from Changes"

            # The exact TOML view is present alongside the semantic view.
            assert str(
                app.query_one("#review-toml-body", Static).render()
            ) == app._document.toml_patch()

    _run(scenario())


def test_exact_toml_view_matches_document_patch(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "renamed"
            await pilot.pause()
            await _goto_review(app, pilot)

            body = app.query_one("#review-toml-body", Static)
            # The TOML view is exactly the patch the document session would write.
            assert str(body.render()) == app._document.toml_patch()

    _run(scenario())


def test_unchanged_fields_are_omitted_from_changes(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-name", Input).value = "demo2"
            await pilot.pause()
            await _goto_review(app, pilot)

            text = _changes_text(app)
            assert "project.name" in text
            # Fields that did not change are not listed.
            assert "aws_region" not in text
            assert "vpc_name" not in text

    _run(scenario())


def test_validation_problem_navigates_to_first_responsible_control(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Introduce a dangling reference: grant the web service access to a
            # bucket that does not exist. The topology flags it and Review blocks
            # the save until it is resolved.
            app._document.set("services[0].s3_access", ["nope"])
            await _goto_review(app, pilot)

            problems = app.query_one("#review-problems")
            assert problems.display is True

            # Saving is blocked and navigates to the owning control (Services).
            await pilot.click("#review-save")
            await pilot.pause()
            await pilot.pause()
            assert app.current_section is Section.SERVICES

    _run(scenario())


def test_review_available_and_reachable(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_review(app, pilot)
            assert app.current_section is Section.REVIEW
            # The Review section renders its three views, not a placeholder.
            assert app.query_one("#review-tabs")
            assert not app.query(".placeholder-message")

    _run(scenario())
