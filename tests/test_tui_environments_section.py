"""The Environments section for the Guided configuration editor (ticket 13).

These Textual Pilot tests drive the Environments editor through the same visible
controls a user operates: the environment master list, the per-environment
override editor (RDS instance type, per-service EC2 instance type, and tags), and
the optional preview-environment panel. They assert persisted TOML through
``load_config`` rather than inspecting private state, and verify that inherited
values are visible without being persisted, that Reset to inherited removes the
override key, that every preview field round-trips (including paired priority
bounds and tags), that invalid preview input is blocked at the responsible field,
and that runtime active-preview data has no editable control.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Checkbox, Collapsible, Input, Select, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.environments import EnvironmentsSection
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import FIELD_REGISTRY, Section

BASE = """\
#:schema ./darth-infra.schema.json
# Hand-formatted project; comments must survive a no-op save.

[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "worker"

[rds]
database_name = "appdb"
instance_type = "db.t4g.micro"
"""

WITH_OVERRIDES = """\
[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000

[rds]
database_name = "appdb"

[environments.staging]
instance_type_override = "db.r6g.large"

[environments.staging.tags]
huit_assetid = "12057"
"""

WITH_PREVIEW = """\
[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000

[preview_environments]
enabled = true
base_environment = "prod"
name_pattern = "pr-{number}"
domain_template = "pr-{number}.example.com"
hosted_zone_name = "example.com"
listener_priority_start = 30000
listener_priority_end = 39999

[preview_environments.tags]
ephemeral-cleanup-id = "{project}-{env}"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_environments(app: ConfigEditorApp, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.ENVIRONMENTS)}")
    await pilot.pause()


async def _select_env(app: ConfigEditorApp, pilot, env: str) -> None:
    from darth_infra.tui.editor.widgets import dom_slug

    await pilot.click(f"#env-btn-{dom_slug(env)}")
    await pilot.pause()


# -- per-environment overrides -----------------------------------------------


def test_edits_every_supported_override_per_environment(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)

            # prod is selected first. Add an environment tag and a per-service
            # EC2 instance override for prod.
            app.query_one(
                "#input-environments-prod-instance-type-override", Input
            ).value = "db.r6g.large"
            app.query_one("#kvkey-environments-prod-tags", Input).value = "team"
            app.query_one("#kvval-environments-prod-tags", Input).value = "platform"
            app.query_one("#kvadd-environments-prod-tags", Button).press()
            await pilot.pause()

            # Per-service EC2 override keyed by an existing service (a dropdown).
            app.query_one(
                "#kvkey-environments-prod-ec2-instance-type-override", Select
            ).value = "web"
            app.query_one(
                "#kvval-environments-prod-ec2-instance-type-override", Input
            ).value = "t3.large"
            app.query_one("#kvadd-environments-prod-ec2-instance-type-override", Button).press()
            await pilot.pause()

            # Switch to staging and give it a different override.
            await _select_env(app, pilot, "staging")
            app.query_one("#kvkey-environments-staging-tags", Input).value = "tier"
            app.query_one("#kvval-environments-staging-tags", Input).value = "beta"
            app.query_one("#kvadd-environments-staging-tags", Button).press()
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    prod = config.environment_overrides["prod"]
    assert prod.instance_type_override == "db.r6g.large"
    assert prod.tags == {"team": "platform"}
    assert prod.ec2_instance_type_override == {"web": "t3.large"}
    assert config.environment_overrides["staging"].tags == {"tier": "beta"}


def test_inherited_values_visible_and_reset_removes_key(tmp_path: Path) -> None:
    path = _write(tmp_path, WITH_OVERRIDES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            await _select_env(app, pilot, "staging")  # staging has the override

            field = app.query_one(
                "#field-environments-staging-instance-type-override"
            )
            badge = _rendered(field.query_one(".field-badge", Static))
            assert "OVERRIDE" in badge
            # The effective inherited base value is shown without being persisted.
            help_text = _rendered(
                field.query_one(
                    "#help-environments-staging-instance-type-override", Static
                )
            )
            assert "Inherited: db.t4g.micro" in help_text

            # Reset to inherited removes the persisted override key.
            await pilot.click("#reset-environments-staging-instance-type-override")
            await pilot.pause()
            badge = _rendered(field.query_one(".field-badge", Static))
            assert "INHERITED" in badge

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    # The override key is gone; the environment inherits the base instance type.
    assert config.environment_overrides["staging"].instance_type_override is None
    # The unrelated environment tag on staging is preserved.
    assert config.environment_overrides["staging"].tags == {"huit_assetid": "12057"}


def test_no_rds_hides_instance_type_override(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[project]\nname = \"demo\"\nenvironments = [\"prod\"]\n\n"
        "[[services]]\nname = \"web\"\n",
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            # No database, so there is no RDS instance-type override control.
            assert not app.query("#field-environments-prod-instance-type-override")
            assert app.query_one("#env-no-rds").display is True

    _run(scenario())


# -- preview environments ----------------------------------------------------


def test_every_preview_field_saves_and_reloads(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)

            app.query_one("#input-preview-environments-enabled", Checkbox).value = True
            app.query_one(
                "#input-preview-environments-base-environment", Input
            ).value = "staging"
            app.query_one(
                "#input-preview-environments-name-pattern", Input
            ).value = "pr-{number}"
            app.query_one(
                "#input-preview-environments-domain-template", Input
            ).value = "pr-{number}.example.com"
            app.query_one(
                "#input-preview-environments-hosted-zone-name", Input
            ).value = "example.com"
            app.query_one(
                "#input-preview-environments-listener-priority-start", Input
            ).value = "30000"
            app.query_one(
                "#input-preview-environments-listener-priority-end", Input
            ).value = "39999"
            app.query_one(
                "#kvkey-preview-environments-tags", Input
            ).value = "ephemeral-cleanup-id"
            app.query_one(
                "#kvval-preview-environments-tags", Input
            ).value = "{project}-{env}"
            app.query_one("#kvadd-preview-environments-tags", Button).press()
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    preview = load_config(path).preview_environments
    assert preview.enabled is True
    assert preview.base_environment == "staging"
    assert preview.name_pattern == "pr-{number}"
    assert preview.domain_template == "pr-{number}.example.com"
    assert preview.hosted_zone_name == "example.com"
    assert preview.listener_priority_start == 30000
    assert preview.listener_priority_end == 39999
    assert preview.tags == {"ephemeral-cleanup-id": "{project}-{env}"}


def test_preview_panel_forced_open_when_configured(tmp_path: Path) -> None:
    path = _write(tmp_path, WITH_PREVIEW)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            panel = app.query_one("#preview-panel", Collapsible)
            assert panel.collapsed is False
            assert "configured" in panel.title

    _run(scenario())


def test_preview_panel_collapsed_when_unconfigured(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            panel = app.query_one("#preview-panel", Collapsible)
            assert panel.collapsed is True

    _run(scenario())


def test_invalid_base_environment_blocks_save_at_field(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            app.query_one("#input-preview-environments-enabled", Checkbox).value = True
            app.query_one(
                "#input-preview-environments-base-environment", Input
            ).value = "does-not-exist"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            error = app.query_one(
                "#error-preview-environments-base-environment", Static
            )
            assert error.display is True

    _run(scenario())

    # Nothing invalid was written.
    assert load_config(path).preview_environments.enabled is False


def test_invalid_priority_pairing_blocks_save_at_field(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            app.query_one("#input-preview-environments-enabled", Checkbox).value = True
            # Start without end: the model requires them set together.
            app.query_one(
                "#input-preview-environments-listener-priority-start", Input
            ).value = "30000"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            error = app.query_one(
                "#error-preview-environments-listener-priority-start", Static
            )
            assert error.display is True

    _run(scenario())

    assert load_config(path).preview_environments.enabled is False


def test_priority_range_ordering_blocks_save(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            app.query_one("#input-preview-environments-enabled", Checkbox).value = True
            app.query_one(
                "#input-preview-environments-listener-priority-start", Input
            ).value = "40000"
            app.query_one(
                "#input-preview-environments-listener-priority-end", Input
            ).value = "30000"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            start_error = app.query_one(
                "#error-preview-environments-listener-priority-start", Static
            )
            assert start_error.display is True

    _run(scenario())

    assert load_config(path).preview_environments.enabled is False


# -- no-op preservation & confidentiality ------------------------------------


def test_noop_save_preserves_document(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(140, 45)) as pilot:
            await _goto_environments(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    text = path.read_text()
    assert "# Hand-formatted project; comments must survive a no-op save." in text
    # No spurious [environments.*] or [preview_environments] tables were added.
    assert "[environments" not in text
    assert "[preview_environments]" not in text


# -- runtime active-preview data is not editable -----------------------------


def test_active_preview_has_no_editable_control() -> None:
    # Runtime-only active-preview metadata is absent from the persisted schema,
    # so no registry entry — and therefore no editable control — targets it.
    for entry in FIELD_REGISTRY:
        assert "active_preview" not in entry.path
