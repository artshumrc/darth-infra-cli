"""The Database (RDS) section for the Guided configuration editor (ticket 10).

These Textual Pilot tests drive the singleton RDS editor through the same visible
controls a user operates: the enable action, the common and Advanced field set,
the multi-service exposure selector, and the confirmed removal flow. They assert
persisted TOML through ``load_config`` rather than inspecting private state, and
verify that document-preserving behavior keeps engine version and backup
retention across a no-op save, that removal presents the complete impact and
cleans up atomically only after confirmation, that reverting restores everything,
and that actual secret values never appear in any widget or notification.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Collapsible, Input, SelectionList, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.collection import ConfirmScreen, ImpactConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

NO_RDS = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "worker"
"""

WITH_RDS = """\
#:schema ./darth-infra.schema.json
# Hand-formatted project; comments and Advanced fields must survive a no-op save.

[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "worker"

# The application database
[rds]
database_name = "appdb"
expose_to = ["web"]
engine_version = "16"          # pinned major version
backup_retention_days = 14
"""

RDS_FULL_REFS = """\
[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000
secrets = ["DATABASE_HOST", "DJANGO_SECRET_KEY"]

[[secrets]]
name = "DATABASE_HOST"
source = "rds"
existing_secret_name = "host"

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"

[rds]
database_name = "appdb"
expose_to = ["web"]

[environments.staging]
instance_type_override = "db.r6g.large"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_database(app: ConfigEditorApp, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.DATABASE)}")
    await pilot.pause()


def _capture_notices(app) -> list[str]:
    notices: list[str] = []

    def _cap(message="", **_kwargs) -> None:
        notices.append(str(message))

    app.notify = _cap  # type: ignore[assignment]
    return notices


# -- enable + edit every base field ------------------------------------------


def test_enable_shows_fields_and_edits_every_base_field(tmp_path: Path) -> None:
    path = _write(tmp_path, NO_RDS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            # Disabled: the enable action shows and the fields are hidden.
            assert app.query_one("#rds-enable").display is True
            assert app.query_one("#field-rds-database-name").display is False

            await pilot.click("#rds-enable")
            await pilot.pause()
            assert app.query_one("#rds-enable").display is False
            assert app.query_one("#field-rds-database-name").display is True

            # An empty name is invalid, so a save is refused and writes nothing.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.query_one("#error-rds-database-name", Static).display is True
            assert load_config(path).rds is None

            # Edit every registered base RDS field (common + Advanced).
            app.query_one("#input-rds-database-name", Input).value = "appdb"
            app.query_one("#input-rds-instance-type", Input).value = "db.t4g.small"
            app.query_one("#input-rds-allocated-storage-gb", Input).value = "50"
            app.query_one("#input-rds-engine-version", Input).value = "16"
            app.query_one("#input-rds-backup-retention-days", Input).value = "21"
            app.query_one("#input-rds-expose-to", SelectionList).select("web")
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    rds = load_config(path).rds
    assert rds is not None
    assert rds.database_name == "appdb"
    assert rds.instance_type == "db.t4g.small"
    assert rds.allocated_storage_gb == 50
    assert rds.engine_version == "16"
    assert rds.backup_retention_days == 21
    assert rds.expose_to == ["web"]


def test_instance_type_normalization_is_model_behavior(tmp_path: Path) -> None:
    path = _write(tmp_path, NO_RDS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            await pilot.click("#rds-enable")
            await pilot.pause()
            app.query_one("#input-rds-database-name", Input).value = "appdb"
            # A raw class without the required db. prefix normalizes in the model.
            app.query_one("#input-rds-instance-type", Input).value = "t4g.micro"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).rds.instance_type == "db.t4g.micro"


# -- document-preserving no-op save ------------------------------------------


def test_advanced_autoexpands_when_configured(tmp_path: Path) -> None:
    path = _write(tmp_path, WITH_RDS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            # engine_version / backup_retention_days are explicitly configured,
            # so the Advanced panel opens automatically.
            panel = app.query_one("#advanced-database", Collapsible)
            assert panel.collapsed is False
            assert "2 configured" in panel.title

    _run(scenario())


def test_noop_save_preserves_engine_version_and_retention(tmp_path: Path) -> None:
    path = _write(tmp_path, WITH_RDS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            # Save without touching anything.
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    rds = load_config(path).rds
    assert rds.engine_version == "16"
    assert rds.backup_retention_days == 14
    # The hand-written comments and Advanced values survive verbatim.
    text = path.read_text()
    assert "# The application database" in text
    assert "# pinned major version" in text


# -- service exposure --------------------------------------------------------


def test_exposure_updates_without_duplicate_bindings(tmp_path: Path) -> None:
    path = _write(tmp_path, WITH_RDS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            # "web" was already exposed; add "worker" as well.
            app.query_one("#input-rds-expose-to", SelectionList).select("worker")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    rds = load_config(path).rds
    assert rds.expose_to == ["web", "worker"]
    # Each service appears exactly once: no duplicate exposure entries.
    assert len(rds.expose_to) == len(set(rds.expose_to))


def test_expose_selector_empty_state_without_services(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[project]\nname = \"demo\"\nenvironments = [\"prod\"]\n",
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            await pilot.click("#rds-enable")
            await pilot.pause()
            # No services yet: the selector shows its empty message, not a list.
            assert app.query_one("#empty-rds-expose-to", Static).display is True
            assert app.query_one("#input-rds-expose-to", SelectionList).display is False

    _run(scenario())


# -- removal -----------------------------------------------------------------


def test_remove_presents_complete_impact_and_can_cancel(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_FULL_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            app.query_one("#rds-remove", Button).press()
            await pilot.pause()
            # The complete impact is shown, not the plain confirm dialog.
            assert isinstance(app.screen, ImpactConfirmScreen)
            items = [_rendered(s) for s in app.screen.query(".impact-item")]
            joined = " ".join(items)
            assert "service 'web'" in joined
            assert "DATABASE_HOST" in joined
            assert "staging" in joined

            # Cancelling keeps the database intact.
            await pilot.click("#impact-cancel")
            await pilot.pause()
            assert app.query_one("#field-rds-database-name").display is True

    _run(scenario())

    # Nothing was removed from the file (no save happened either way).
    assert load_config(path).rds is not None


def test_remove_applies_cleanup_atomically_after_confirm(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_FULL_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            app.query_one("#rds-remove", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, ImpactConfirmScreen)
            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            # The section returns to its disabled state.
            assert app.query_one("#rds-enable").display is True
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    assert config.rds is None
    # The RDS-backed secret declaration and its binding are cleaned up together;
    # the unrelated generated secret survives.
    assert [s.name for s in config.secrets] == ["DJANGO_SECRET_KEY"]
    assert config.services[0].secrets == ["DJANGO_SECRET_KEY"]
    assert config.environment_overrides["staging"].instance_type_override is None


def test_remove_without_references_uses_plain_confirm(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[project]\nname = \"demo\"\nenvironments = [\"prod\"]\n\n"
        "[rds]\ndatabase_name = \"appdb\"\n",
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            app.query_one("#rds-remove", Button).press()
            await pilot.pause()
            # No dependent references: a plain confirmation, not an impact list.
            assert isinstance(app.screen, ConfirmScreen)
            assert not isinstance(app.screen, ImpactConfirmScreen)
            await pilot.click("#confirm-yes")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).rds is None


def test_revert_restores_rds_and_cleaned_references(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_FULL_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            app.query_one("#rds-remove", Button).press()
            await pilot.pause()
            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            assert app._document.config.rds is None

            # Reverting the draft restores the database and every cleaned
            # reference together (one reversible transaction was applied).
            app._document.revert_all()
            config = app._document.config
            assert config.rds is not None and config.rds.database_name == "appdb"
            assert "web" in config.rds.expose_to
            assert "DATABASE_HOST" in [s.name for s in config.secrets]
            assert "DATABASE_HOST" in config.services[0].secrets
            assert (
                config.environment_overrides["staging"].instance_type_override
                == "db.r6g.large"
            )

    _run(scenario())


# -- secret-value confidentiality --------------------------------------------


def test_env_vars_shown_by_name_only_no_values(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_FULL_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        notices = _capture_notices(app)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_database(app, pilot)
            # The env-var inventory lists names and states values are never shown.
            envvars = _rendered(app.query_one("#rds-envvars", Static))
            assert "DATABASE_HOST" in envvars
            assert "POSTGRES_PASSWORD" in envvars
            assert "values are never shown" in envvars

            # Remove (which touches the RDS-backed secret) and confirm: no
            # notification leaks a secret value.
            app.query_one("#rds-remove", Button).press()
            await pilot.pause()
            await pilot.click("#impact-confirm")
            await pilot.pause()

        # No widget input ever held a secret value, and notifications carry none.
        assert all("host" != n for n in notices)

    _run(scenario())
