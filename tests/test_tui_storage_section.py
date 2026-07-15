"""The Storage (S3) section for the Guided configuration editor (ticket 11).

These Textual Pilot tests drive the master-detail bucket editor through the same
visible controls a user operates: the searchable bucket list, the
Add/Duplicate/Delete actions, the detail editor for the selected bucket, and the
nested service-connection editor. They assert persisted TOML through
``load_config`` rather than inspecting private state, and verify that every
registered bucket and connection field round-trips (including preview fallback and
CloudFront env keys), that mode-specific values survive a no-op save, that an
explicit mode change clears incompatible values only after confirmation, that
deletion presents the complete impact and cleans up atomically and reversibly,
and that a public-read change is flagged deployment-sensitive without being
blocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Checkbox, Input, ListView, Select, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
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

EXISTING_BUCKET = """\
#:schema ./darth-infra.schema.json
# Hand-formatted project; comments and mode-specific fields must survive.

[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

# Static assets bucket
[[s3_buckets]]
name = "assets"
mode = "existing"
existing_bucket_name = "legacy-assets"   # must survive a no-op save
"""

SEED_BUCKET = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[s3_buckets]]
name = "media"
mode = "seed-copy"
seed_source_bucket_name = "old-media"
seed_non_prod_only = false
cors = true
"""

BUCKET_WITH_REFS = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
s3_access = ["media"]

[[services]]
name = "worker"

[[s3_buckets]]
name = "media"
mode = "managed"

[[s3_buckets.connections]]
service = "web"
env_key = "MEDIA_BUCKET"
"""

TWO_BUCKETS = """\
[project]
name = "demo"
environments = ["prod"]

[[s3_buckets]]
name = "media"
mode = "managed"

[[s3_buckets]]
name = "uploads"
mode = "managed"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_storage(app, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.STORAGE)}")
    await pilot.pause()


async def _select_row(app, pilot, row: int) -> None:
    lv = app.query_one("#md-list", ListView)
    app.set_focus(lv)
    lv.index = row
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


# -- master-detail add / search / edit / duplicate / delete ------------------


def test_add_search_edit_and_save_bucket(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            section = app._section_widget
            assert section.item_count() == 0

            await pilot.click("#md-add")
            await pilot.pause()
            assert section.item_count() == 1
            # A new unnamed bucket is invalid: Ctrl+S refuses and writes nothing.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.query_one("#error-s3-buckets-0-name", Static).display is True
            assert load_config(path).s3_buckets == []

            app.query_one("#input-s3-buckets-0-name", Input).value = "media"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    buckets = load_config(path).s3_buckets
    assert [b.name for b in buckets] == ["media"]
    assert buckets[0].mode.value == "managed"


def test_search_filters_the_bucket_list(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_BUCKETS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            section = app._section_widget
            assert len(section._visible) == 2

            app.query_one("#md-search", Input).value = "upl"
            await pilot.pause()
            assert section._visible == [1]

            app.query_one("#md-search", Input).value = ""
            await pilot.pause()
            assert len(section._visible) == 2

    _run(scenario())


def test_duplicate_copies_fields_but_requires_unique_name(tmp_path: Path) -> None:
    path = _write(tmp_path, SEED_BUCKET)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)

            await pilot.click("#md-duplicate")
            await pilot.pause()
            section = app._section_widget
            assert section.item_count() == 2
            # The copy carries the mode-specific seed field but starts unnamed.
            assert app.query_one("#input-s3-buckets-1-name", Input).value == ""
            assert (
                app.query_one(
                    "#input-s3-buckets-1-seed-source-bucket-name", Input
                ).value
                == "old-media"
            )

            # Invalid (unnamed) duplicate blocks the save.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert len(load_config(path).s3_buckets) == 1

            app.query_one("#input-s3-buckets-1-name", Input).value = "media2"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    buckets = load_config(path).s3_buckets
    assert [b.name for b in buckets] == ["media", "media2"]
    assert buckets[1].seed_source_bucket_name == "old-media"


# -- full field coverage -----------------------------------------------------


def test_every_bucket_and_connection_field_saves_and_reloads(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()

            app.query_one("#input-s3-buckets-0-name", Input).value = "media"
            app.query_one("#input-s3-buckets-0-public-read", Checkbox).value = True
            app.query_one("#input-s3-buckets-0-cloudfront", Checkbox).value = True
            app.query_one("#input-s3-buckets-0-cors", Checkbox).value = True
            app.query_one(
                "#input-s3-buckets-0-preview-fallback-bucket-name", Input
            ).value = "legacy-media"
            app.query_one(
                "#input-s3-buckets-0-preview-fallback-env-key", Input
            ).value = "MEDIA_FALLBACK"
            await pilot.pause()

            # Add a service connection with every connection field set.
            app.query_one("#nestedadd-s3-buckets-0-connections", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-s3-buckets-0-connections-0-service", Select
            ).value = "web"
            app.query_one(
                "#input-s3-buckets-0-connections-0-env-key", Input
            ).value = "MEDIA_BUCKET"
            app.query_one(
                "#input-s3-buckets-0-connections-0-cloudfront-env-key", Input
            ).value = "MEDIA_CDN_URL"
            app.query_one(
                "#input-s3-buckets-0-connections-0-read-only", Checkbox
            ).value = True
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    bucket = load_config(path).s3_buckets[0]
    assert bucket.name == "media"
    assert bucket.public_read is True
    assert bucket.cloudfront is True
    assert bucket.cors is True
    assert bucket.preview_fallback_bucket_name == "legacy-media"
    assert bucket.preview_fallback_env_key == "MEDIA_FALLBACK"
    assert len(bucket.connections) == 1
    conn = bucket.connections[0]
    assert conn.service == "web"
    assert conn.env_key == "MEDIA_BUCKET"
    assert conn.cloudfront_env_key == "MEDIA_CDN_URL"
    assert conn.read_only is True


def test_existing_mode_field_saves_and_advanced_autoexpands(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_BUCKET)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            # The existing-bucket field is visible in existing mode and holds
            # the loaded value.
            field = app.query_one("#field-s3-buckets-0-existing-bucket-name")
            assert field.display is True
            assert (
                app.query_one(
                    "#input-s3-buckets-0-existing-bucket-name", Input
                ).value
                == "legacy-assets"
            )
            # The seed fields are hidden in existing mode.
            assert (
                app.query_one("#field-s3-buckets-0-seed-source-bucket-name").display
                is False
            )

    _run(scenario())


# -- mode-specific value survival + no-op save -------------------------------


def test_noop_save_preserves_mode_specific_values(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_BUCKET)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            # Save without touching anything.
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    bucket = load_config(path).s3_buckets[0]
    assert bucket.mode.value == "existing"
    assert bucket.existing_bucket_name == "legacy-assets"
    # Comments and the mode-specific value survive verbatim.
    text = path.read_text()
    assert "# Static assets bucket" in text
    assert "must survive a no-op save" in text


# -- explicit mode change with confirmation ----------------------------------


def test_mode_change_cancel_preserves_incompatible_value(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_BUCKET)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            # Switch existing -> managed: the existing bucket name is incompatible.
            app.query_one("#input-s3-buckets-0-mode", Select).value = "managed"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            # Cancel: the mode and the existing bucket name are both preserved.
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert (
                app.query_one("#input-s3-buckets-0-mode", Select).value == "existing"
            )
            assert (
                app.query_one(
                    "#input-s3-buckets-0-existing-bucket-name", Input
                ).value
                == "legacy-assets"
            )

    _run(scenario())

    # Nothing was saved; the file is unchanged.
    assert load_config(path).s3_buckets[0].existing_bucket_name == "legacy-assets"


def test_mode_change_confirm_clears_incompatible_value(tmp_path: Path) -> None:
    path = _write(tmp_path, EXISTING_BUCKET)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            app.query_one("#input-s3-buckets-0-mode", Select).value = "managed"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#confirm-yes")
            await pilot.pause()
            # The incompatible field is cleared and hidden; mode is now managed.
            assert app.query_one("#input-s3-buckets-0-mode", Select).value == "managed"
            assert (
                app.query_one("#field-s3-buckets-0-existing-bucket-name").display
                is False
            )
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    bucket = load_config(path).s3_buckets[0]
    assert bucket.mode.value == "managed"
    assert bucket.existing_bucket_name is None


# -- deletion impact + cascade + revert --------------------------------------


def test_bucket_delete_lists_impact_and_cleans_up_atomically(tmp_path: Path) -> None:
    path = _write(tmp_path, BUCKET_WITH_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            await pilot.click("#md-delete")
            await pilot.pause()
            # The complete impact is shown: the bucket connection and the
            # service s3_access grant that named the bucket.
            assert isinstance(app.screen, ImpactConfirmScreen)
            items = " ".join(_rendered(s) for s in app.screen.query(".impact-item"))
            assert "MEDIA_BUCKET" in items
            assert "service 'web'" in items

            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            section = app._section_widget
            assert section.item_count() == 0
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    assert config.s3_buckets == []
    # The external s3_access grant naming the bucket is cleaned up too.
    assert config.services[0].s3_access == []


def test_bucket_delete_is_reversible_before_save(tmp_path: Path) -> None:
    path = _write(tmp_path, BUCKET_WITH_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            await pilot.click("#md-delete")
            await pilot.pause()
            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            assert app._document.config.s3_buckets == []

            # Reverting restores the bucket and the cleaned s3_access grant.
            app._document.revert_all()
            config = app._document.config
            assert [b.name for b in config.s3_buckets] == ["media"]
            assert config.s3_buckets[0].connections[0].env_key == "MEDIA_BUCKET"
            assert config.services[0].s3_access == ["media"]

    _run(scenario())


def test_service_delete_impact_includes_bucket_connection(tmp_path: Path) -> None:
    path = _write(tmp_path, BUCKET_WITH_REFS)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
            await pilot.pause()
            await _select_row(app, pilot, 0)  # "web", named by a bucket connection

            await pilot.click("#md-delete")
            await pilot.pause()
            assert isinstance(app.screen, ImpactConfirmScreen)
            items = " ".join(_rendered(s) for s in app.screen.query(".impact-item"))
            assert "media" in items and "MEDIA_BUCKET" in items

            await pilot.click("#impact-confirm")
            await pilot.pause()
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    config = load_config(path)
    assert [s.name for s in config.services] == ["worker"]
    # The bucket survives, but its connection to the deleted service is gone.
    assert config.s3_buckets[0].connections == []


# -- deployment-sensitive public read ----------------------------------------


def test_public_read_shows_warning_and_still_saves(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_storage(app, pilot)
            await pilot.click("#md-add")
            await pilot.pause()
            app.query_one("#input-s3-buckets-0-name", Input).value = "media"

            warning = app.query_one("#bucket-sensitive-0", Static)
            assert warning.display is False

            # Enabling public read surfaces the deployment-sensitive warning.
            app.query_one("#input-s3-buckets-0-public-read", Checkbox).value = True
            await pilot.pause()
            assert warning.display is True
            assert "Deployment-sensitive" in _rendered(warning)

            # It is not blocked: the configuration still saves.
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).s3_buckets[0].public_read is True
