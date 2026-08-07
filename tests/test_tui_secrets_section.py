"""The Secrets section for the Guided configuration editor (ticket 12).

These Textual Pilot tests drive the master-detail secret editor through the same
visible controls a user operates: the searchable secret list, the
Add/Duplicate/Delete actions, the detail editor for the selected secret, the
source-specific conditional panels, the AWS existing-secret picker, and the
reverse service-binding selector. They assert persisted TOML through
``load_config`` rather than inspecting private state, and verify that every
registered secret field and service binding round-trips, that each of the four
sources behaves correctly, that discovery lists names/ARNs only while manual
entry works offline, that deleting a bound secret presents the complete impact
and cleans it up atomically and reversibly, and that the editor never retrieves
or renders a secret value.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Input, ListView, Select, SelectionList, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.config.models import SecretSource
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.aws_discovery import (
    DiscoveryKind,
    DiscoveryResult,
    FakeAwsDiscovery,
    OfflineAwsDiscovery,
    ResourceRecord,
)
from darth_infra.tui.editor.collection import ConfirmScreen, ImpactConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

ONE_SERVICE = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
"""

EXISTING_SECRET = """\
#:schema ./darth-infra.schema.json
# Hand-formatted project; comments and the secret must survive.

[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

# API key from Secrets Manager
[[secrets]]
name = "API_KEY"
source = "existing"
existing_secret_name = "prod/api-key"   # must survive a no-op save
"""

BOUND_SECRET = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
secrets = ["API_KEY"]

[[services]]
name = "worker"
secrets = ["API_KEY"]

[[secrets]]
name = "API_KEY"
source = "generate"
"""

TWO_SECRETS = """\
[project]
name = "demo"
environments = ["prod"]

[[secrets]]
name = "API_KEY"
source = "generate"

[[secrets]]
name = "DB_PASSWORD"
source = "generate"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_secrets(app, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.SECRETS)}")
    await pilot.pause()


def _make_app(path: Path, discovery=None) -> ConfigEditorApp:
    kwargs = {"document": ProjectDocument.load(path)}
    if discovery is not None:
        kwargs["discovery"] = discovery
    return ConfigEditorApp(**kwargs)


# -- master-detail add / search / edit / duplicate / delete ------------------


def test_add_edit_and_save_generate_secret(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            section = app._section_widget
            assert section.item_count() == 0

            await pilot.click("#md-add")
            await pilot.pause()
            assert section.item_count() == 1
            # An unnamed secret is invalid: Ctrl+S refuses and writes nothing.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.query_one("#error-secrets-0-name", Static).display is True
            assert load_config(path).secrets == []

            app.query_one("#input-secrets-0-name", Input).value = "DJANGO_SECRET_KEY"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secrets = load_config(path).secrets
    assert [s.name for s in secrets] == ["DJANGO_SECRET_KEY"]
    assert secrets[0].source is SecretSource.GENERATE


def test_search_filters_the_secret_list(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SECRETS)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            section = app._section_widget
            assert len(section._visible) == 2

            app.query_one("#md-search", Input).value = "DB"
            await pilot.pause()
            assert section._visible == [1]

            app.query_one("#md-search", Input).value = ""
            await pilot.pause()
            assert len(section._visible) == 2

    _run(scenario())


# -- full field coverage -----------------------------------------------------


def test_generate_secret_length_and_binding_save_and_reload(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()

            app.query_one("#input-secrets-0-name", Input).value = "DJANGO_SECRET_KEY"
            # length + generate_once live in the Advanced panel.
            app.query_one("#input-secrets-0-length", Input).value = "64"
            await pilot.pause()
            # generate_once checkbox is present and defaults to true.
            assert app.query_one("#input-secrets-0-generate-once").value is True

            # Bind the secret to the "web" service via the reverse selector.
            app.query_one("#input-secrets-0-bindings", SelectionList).select("0")
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    secret = config.secrets[0]
    assert secret.name == "DJANGO_SECRET_KEY"
    assert secret.source is SecretSource.GENERATE
    assert secret.length == 64
    assert secret.generate_once is True
    # The reverse binding landed on the service's own secrets list.
    assert config.services[0].secrets == ["DJANGO_SECRET_KEY"]


def test_existing_source_name_and_binding_save_and_reload(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()

            app.query_one("#input-secrets-0-name", Input).value = "API_KEY"
            app.query_one("#input-secrets-0-source", Select).value = "existing"
            await pilot.pause()
            # The existing-secret field is now visible.
            assert app.query_one("#field-secrets-0-existing-secret-name").display is True
            app.query_one(
                "#input-secrets-0-existing-secret-name", Input
            ).value = "prod/api-key"
            app.query_one("#input-secrets-0-bindings", SelectionList).select("0")
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    secret = config.secrets[0]
    assert secret.source is SecretSource.EXISTING
    assert secret.existing_secret_name == "prod/api-key"
    assert config.services[0].secrets == ["API_KEY"]


def test_rds_source_saves_json_key_and_hides_discovery(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path, discovery=FakeAwsDiscovery())
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()

            app.query_one("#input-secrets-0-name", Input).value = "DB_PASSWORD"
            app.query_one("#input-secrets-0-source", Select).value = "rds"
            await pilot.pause()
            # The value field is shown, but AWS discovery does not apply to a
            # JSON key, so its picker is hidden.
            assert app.query_one("#field-secrets-0-existing-secret-name").display is True
            assert (
                app.query_one("#discover-secrets-0-existing-secret-name").display
                is False
            )
            app.query_one(
                "#input-secrets-0-existing-secret-name", Input
            ).value = "password"
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secret = load_config(path).secrets[0]
    assert secret.source is SecretSource.RDS
    assert secret.existing_secret_name == "password"


def test_env_source_hides_value_shows_note_and_persists_no_name(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()

            app.query_one("#input-secrets-0-name", Input).value = "SENTRY_DSN"
            app.query_one("#input-secrets-0-source", Select).value = "env"
            await pilot.pause()
            # No value is collected; an explanatory note is shown instead.
            assert (
                app.query_one("#field-secrets-0-existing-secret-name").display is False
            )
            note = app.query_one("#secret-env-note-0", Static)
            assert note.display is True
            assert "local environment" in _rendered(note)

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secret = load_config(path).secrets[0]
    assert secret.source is SecretSource.ENV
    assert secret.existing_secret_name is None


def test_all_four_sources_can_be_added(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            specs = [
                ("GEN", "generate", None),
                ("ENVREF", "env", None),
                ("EXIST", "existing", "prod/x"),
                ("RDSKEY", "rds", "password"),
            ]
            for i, (name, source, value) in enumerate(specs):
                await pilot.click("#md-add")
                await pilot.pause()
                app.query_one(f"#input-secrets-{i}-name", Input).value = name
                app.query_one(f"#input-secrets-{i}-source", Select).value = source
                await pilot.pause()
                if value is not None:
                    app.query_one(
                        f"#input-secrets-{i}-existing-secret-name", Input
                    ).value = value
                    await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secrets = load_config(path).secrets
    assert [s.source for s in secrets] == [
        SecretSource.GENERATE,
        SecretSource.ENV,
        SecretSource.EXISTING,
        SecretSource.RDS,
    ]


# -- no-op save preserves the existing declaration ---------------------------


def test_noop_save_preserves_existing_secret(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secret = load_config(path).secrets[0]
    assert secret.source is SecretSource.EXISTING
    assert secret.existing_secret_name == "prod/api-key"
    text = path.read_text()
    assert "# API key from Secrets Manager" in text
    assert "must survive a no-op save" in text


# -- duplicate ---------------------------------------------------------------


def test_duplicate_copies_source_but_requires_unique_name(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)

            await pilot.click("#md-duplicate")
            await pilot.pause()
            section = app._section_widget
            assert section.item_count() == 2
            # The copy carries the source metadata but starts unnamed.
            assert app.query_one("#input-secrets-1-name", Input).value == ""
            assert (
                app.query_one(
                    "#input-secrets-1-existing-secret-name", Input
                ).value
                == "prod/api-key"
            )

            # Invalid (unnamed) duplicate blocks the save.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert len(load_config(path).secrets) == 1

            app.query_one("#input-secrets-1-name", Input).value = "API_KEY_2"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secrets = load_config(path).secrets
    assert [s.name for s in secrets] == ["API_KEY", "API_KEY_2"]
    assert secrets[1].source is SecretSource.EXISTING
    assert secrets[1].existing_secret_name == "prod/api-key"


# -- source change with confirmation -----------------------------------------


def test_source_change_cancel_preserves_incompatible_value(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            # existing -> generate: the existing name/ARN is incompatible.
            app.query_one("#input-secrets-0-source", Select).value = "generate"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#confirm-no")
            await pilot.pause()
            assert (
                app.query_one("#input-secrets-0-source", Select).value == "existing"
            )
            assert (
                app.query_one(
                    "#input-secrets-0-existing-secret-name", Input
                ).value
                == "prod/api-key"
            )

    _run(scenario())

    assert load_config(path).secrets[0].existing_secret_name == "prod/api-key"


def test_source_change_confirm_clears_incompatible_value(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            app.query_one("#input-secrets-0-source", Select).value = "generate"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#confirm-yes")
            await pilot.pause()
            assert app.query_one("#input-secrets-0-source", Select).value == "generate"
            assert (
                app.query_one("#field-secrets-0-existing-secret-name").display is False
            )
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    secret = load_config(path).secrets[0]
    assert secret.source is SecretSource.GENERATE
    assert secret.existing_secret_name is None


# -- deletion impact + cascade + revert --------------------------------------


def test_secret_delete_lists_binding_impact_and_cleans_up(tmp_path: Path) -> None:
    path = _write(tmp_path, BOUND_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-delete")
            await pilot.pause()
            # The complete impact lists every service binding to the secret.
            assert isinstance(app.screen, ImpactConfirmScreen)
            items = " ".join(_rendered(s) for s in app.screen.query(".impact-item"))
            assert "service 'web'" in items
            assert "service 'worker'" in items

            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            section = app._section_widget
            assert section.item_count() == 0
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    assert config.secrets == []
    # Every binding that named the secret is cleaned up too.
    assert config.services[0].secrets == []
    assert config.services[1].secrets == []


def test_secret_delete_is_reversible_before_save(tmp_path: Path) -> None:
    path = _write(tmp_path, BOUND_SECRET)

    async def scenario() -> None:
        app = _make_app(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-delete")
            await pilot.pause()
            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            assert app._document.config.secrets == []

            # Reverting restores the secret and both cleaned bindings.
            app._document.revert_all()
            config = app._document.config
            assert [s.name for s in config.secrets] == ["API_KEY"]
            assert config.services[0].secrets == ["API_KEY"]
            assert config.services[1].secrets == ["API_KEY"]

    _run(scenario())


# -- AWS discovery states + offline manual entry -----------------------------


def test_existing_secret_discovery_results_fill_field(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.SECRET: DiscoveryResult.of(
                [
                    ResourceRecord(
                        "prod/api-key",
                        "prod/api-key (arn:secret:1)",
                        {"arn": "arn:secret:1"},
                    )
                ]
            )
        }
    )

    async def scenario() -> None:
        app = _make_app(path, discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()
            app.query_one("#input-secrets-0-name", Input).value = "API_KEY"
            app.query_one("#input-secrets-0-source", Select).value = "existing"
            await pilot.pause()

            app.query_one("#discover-secrets-0-existing-secret-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#discstatus-secrets-0-existing-secret-name", Static)
            assert "found" in _rendered(status).lower()

            # Selecting a discovered record fills the field.
            app.query_one(
                "#select-secrets-0-existing-secret-name", Select
            ).value = "prod/api-key"
            await pilot.pause()
            assert (
                app.query_one(
                    "#input-secrets-0-existing-secret-name", Input
                ).value
                == "prod/api-key"
            )
            # A SECRET discovery request was issued.
            assert any(r.kind is DiscoveryKind.SECRET for r in fake.requests)

    _run(scenario())


def test_existing_secret_discovery_empty_and_failure_states(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario(fake, needle) -> None:
        app = _make_app(path, discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()
            app.query_one("#input-secrets-0-source", Select).value = "existing"
            await pilot.pause()
            app.query_one("#discover-secrets-0-existing-secret-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#discstatus-secrets-0-existing-secret-name", Static)
            assert needle in _rendered(status).lower()

    _run(
        scenario(
            FakeAwsDiscovery(results={DiscoveryKind.SECRET: DiscoveryResult.of([])}),
            "no matching",
        )
    )
    _run(
        scenario(
            FakeAwsDiscovery(
                results={DiscoveryKind.SECRET: DiscoveryResult.failed("no creds")}
            ),
            "failed",
        )
    )


def test_offline_manual_entry_saves_existing_secret(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = _make_app(path, discovery=OfflineAwsDiscovery())
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_secrets(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()
            app.query_one("#input-secrets-0-name", Input).value = "API_KEY"
            app.query_one("#input-secrets-0-source", Select).value = "existing"
            await pilot.pause()
            # Discovery fails offline, but manual entry still works and saves.
            app.query_one("#discover-secrets-0-existing-secret-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#discstatus-secrets-0-existing-secret-name", Static)
            assert "failed" in _rendered(status).lower()

            app.query_one(
                "#input-secrets-0-existing-secret-name", Input
            ).value = "typed/secret"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).secrets[0].existing_secret_name == "typed/secret"
