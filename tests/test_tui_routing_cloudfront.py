"""CloudFront routing-section behavior for the Guided editor (ticket 09).

These Textual Pilot tests drive CloudFront through its visible controls: the
enable toggle, the advanced scalar panel (origin HTTPS-only, custom domain,
certificate ARN, price class, comment), the service-connection collection, and
the master-detail cached-behavior editor with its conditional query-string and
cookie allowlists. They assert persisted TOML through ``load_config`` and the
document text, never private widget state.

CloudFront settings stay hidden behind the enable control but existing values
force the panel open and are never discarded by navigation. Certificate input
supports offline manual entry and searchable AWS discovery through the injected
fake adapter. The model's cross-field rules (TTL ordering, allowlist modes,
domain/certificate pairing, duplicate identities) remain authoritative and block
a save at the responsible field.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.widgets import Button, Checkbox, Collapsible, Input, Select, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.review import RiskConfirmScreen
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

_CERT = "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"

# A shared-ALB project with routing configured but no CloudFront yet.
ROUTED = """\
#:schema ./darth-infra.schema.json
# A hand-formatted project. Comments and ordering must survive edits.

[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "api"
port = 9000

[alb]
mode = "shared"
shared_alb_name = "prod-shared-alb"
domain = "demo.example.com"
default_target_service = "web"
"""

# An existing project with complete, non-default CloudFront configuration.
CF_CONFIGURED = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "api"
port = 9000

[alb]
mode = "shared"
shared_alb_name = "prod-shared-alb"
domain = "demo.example.com"
default_target_service = "web"

[cloudfront]
enabled = true
origin_https_only = true
price_class = "PriceClass_200"
comment = "cdn for demo"

[[cloudfront.connections]]
service = "api"
env_key = "CDN_API_URL"

[[cloudfront.cached_behaviors]]
name = "images"
path_pattern = "/images/*"
compress = false
cache_by_origin_headers = false
min_ttl_seconds = 10
default_ttl_seconds = 100
max_ttl_seconds = 1000
query_strings = "allowlist"
query_string_allowlist = ["v", "page"]
cookies = "allowlist"
cookie_allowlist = ["session"]
forward_authorization_header = true
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


async def _ctrl_s(app, pilot) -> None:
    """Press Ctrl+S and confirm the risk dialog when a deployment-sensitive
    change raises one. The save/risk flow is unified across sections in
    ticket 15, so any save touching managed identity confirms before writing."""
    await pilot.press("ctrl+s")
    await pilot.pause()
    if isinstance(app.screen, RiskConfirmScreen):
        await pilot.click("#risk-confirm")
        await pilot.pause()
    await pilot.pause()


def _run(coro) -> None:
    asyncio.run(coro)


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_routing(app, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.ROUTING)}")
    await pilot.pause()


def _panel(app):
    return app.query_one("#cloudfront-panel")


def _cf(name: str) -> str:
    return f"cloudfront-cached-behaviors-0-{name}"


async def _add_valid_behavior(app, pilot, *, index: int = 0) -> None:
    """Add a cached behavior with a unique valid name/path so cloudfront saves."""
    app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
    await pilot.pause()
    app.query_one(
        f"#input-cloudfront-cached-behaviors-{index}-name", Input
    ).value = f"behavior-{index}"
    app.query_one(
        f"#input-cloudfront-cached-behaviors-{index}-path-pattern", Input
    ).value = f"/b{index}/*"
    await pilot.pause()


# -- enable gate + panel visibility ------------------------------------------


def test_panel_hidden_until_enabled(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            # No CloudFront config and disabled: the panel is hidden.
            assert _panel(app).display is False

            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            # Enabling reveals the panel.
            assert _panel(app).display is True

    _run(scenario())


def test_existing_config_forces_panel_open_even_when_disabled(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            assert _panel(app).display is True

            # Unchecking enabled must not conceal existing configuration.
            app.query_one("#input-cloudfront-enabled", Checkbox).value = False
            await pilot.pause()
            assert _panel(app).display is True

    _run(scenario())


def test_existing_config_survives_navigation_away_and_back(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await pilot.click(f"#{nav_button_id(Section.NETWORK)}")
            await pilot.pause()
            await _goto_routing(app, pilot)
            assert _panel(app).display is True
            # The draft still holds the original CloudFront configuration.
            assert app._document.record_count("cloudfront.cached_behaviors") == 1
            assert app._document.is_explicit("cloudfront.comment") is True

    _run(scenario())


# -- no-op save --------------------------------------------------------------


def test_existing_cloudfront_survives_noop_save_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)
    before = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await _ctrl_s(app, pilot)

    _run(scenario())

    assert path.read_text() == before
    cfg = load_config(path)
    assert cfg.cloudfront.enabled is True
    assert cfg.cloudfront.origin_https_only is True
    assert cfg.cloudfront.price_class == "PriceClass_200"
    assert cfg.cloudfront.comment == "cdn for demo"
    assert cfg.cloudfront.connections[0].env_key == "CDN_API_URL"
    behavior = cfg.cloudfront.cached_behaviors[0]
    assert behavior.query_string_allowlist == ["v", "page"]
    assert behavior.cookie_allowlist == ["session"]


# -- scalar round-tripping ---------------------------------------------------


def test_enable_and_edit_scalar_fields_round_trip(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#advanced-cloudfront", Collapsible).collapsed = False
            await pilot.pause()

            app.query_one(
                "#input-cloudfront-origin-https-only", Checkbox
            ).value = True
            app.query_one(
                "#input-cloudfront-price-class", Select
            ).value = "PriceClass_All"
            app.query_one(
                "#input-cloudfront-comment", Input
            ).value = "edge cache"
            await pilot.pause()

            await _add_valid_behavior(app, pilot)
            await _ctrl_s(app, pilot)

    _run(scenario())

    cfg = load_config(path)
    assert cfg.cloudfront.enabled is True
    assert cfg.cloudfront.origin_https_only is True
    assert cfg.cloudfront.price_class == "PriceClass_All"
    assert cfg.cloudfront.comment == "edge cache"
    assert len(cfg.cloudfront.cached_behaviors) == 1


# -- certificate: manual entry + discovery -----------------------------------


def test_certificate_manual_entry_offline(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(
            document=ProjectDocument.load(path), discovery=OfflineAwsDiscovery()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#advanced-cloudfront", Collapsible).collapsed = False
            await pilot.pause()

            app.query_one(
                "#input-cloudfront-custom-domain", Input
            ).value = "cdn.example.com"
            app.query_one(
                "#input-cloudfront-certificate-arn", Input
            ).value = _CERT
            await pilot.pause()

            await _add_valid_behavior(app, pilot)
            await _ctrl_s(app, pilot)

    _run(scenario())

    cfg = load_config(path)
    assert cfg.cloudfront.custom_domain == "cdn.example.com"
    assert cfg.cloudfront.certificate_arn == _CERT


def test_certificate_discovery_fills_the_field(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)
    release = threading.Event()
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.CERTIFICATE: DiscoveryResult.of(
                [ResourceRecord(_CERT, f"cdn.example.com ({_CERT})")]
            )
        },
        gate=lambda: release.wait(5),
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#advanced-cloudfront", Collapsible).collapsed = False
            await pilot.pause()

            app.query_one("#discover-cloudfront-certificate-arn", Button).press()
            await pilot.pause()
            status = app.query_one("#discstatus-cloudfront-certificate-arn", Static)
            assert "loading" in _rendered(status).lower()

            release.set()
            await pilot.pause()
            await pilot.pause()
            assert "found" in _rendered(status).lower()

            app.query_one(
                "#select-cloudfront-certificate-arn", Select
            ).value = _CERT
            await pilot.pause()
            assert (
                app.query_one("#input-cloudfront-certificate-arn", Input).value
                == _CERT
            )
            # The discovery request was issued through the injected adapter.
            assert fake.requests[-1].kind is DiscoveryKind.CERTIFICATE

    _run(scenario())


# -- service connections -----------------------------------------------------


def test_connection_add_edit_duplicate_delete(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            await _add_valid_behavior(app, pilot)

            # Add a connection.
            app.query_one("#nestedadd-cloudfront-connections", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-cloudfront-connections-0-service", Select
            ).value = "web"
            app.query_one(
                "#input-cloudfront-connections-0-env-key", Input
            ).value = "CDN_URL"
            await pilot.pause()

            # Duplicate it, then give the copy a distinct env key.
            app.query_one("#nesteddup-cloudfront-connections", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-cloudfront-connections-1-env-key", Input
            ).value = "CDN_ALT_URL"
            await pilot.pause()

            await _ctrl_s(app, pilot)

    _run(scenario())

    cfg = load_config(path)
    conns = cfg.cloudfront.connections
    assert len(conns) == 2
    assert {c.env_key for c in conns} == {"CDN_URL", "CDN_ALT_URL"}
    assert all(c.service == "web" for c in conns)


def test_connection_service_cascade_on_service_delete(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)  # connection points at 'api'

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
            await pilot.pause()

            # Select the 'api' service (index 1) and delete it.
            app._section_widget._selected = 1  # noqa: SLF001
            app.query_one("#md-delete", Button).press()
            await pilot.pause()
            # Deleting a referenced service lists the CloudFront connection.
            assert isinstance(app.screen, ImpactConfirmScreen)
            body = " ".join(_rendered(s) for s in app.screen.query(Static))
            assert "CloudFront connection" in body
            await pilot.click("#impact-confirm")
            await pilot.pause()

            await _ctrl_s(app, pilot)

    _run(scenario())

    cfg = load_config(path)
    assert [s.name for s in cfg.services] == ["web"]
    # The dangling CloudFront connection was cleaned up atomically.
    assert cfg.cloudfront.connections == []


# -- cached behaviors: full round-trip + conditional allowlists --------------


def test_cached_behavior_round_trips_every_field(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()

            app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
            await pilot.pause()
            app.query_one(f"#input-{_cf('name')}", Input).value = "assets"
            app.query_one(f"#input-{_cf('path-pattern')}", Input).value = "/assets/*"
            await pilot.pause()
            app.query_one(f"#input-{_cf('compress')}", Checkbox).value = False
            app.query_one(
                f"#input-{_cf('cache-by-origin-headers')}", Checkbox
            ).value = False
            app.query_one(f"#input-{_cf('min-ttl-seconds')}", Input).value = "5"
            app.query_one(f"#input-{_cf('default-ttl-seconds')}", Input).value = "50"
            app.query_one(f"#input-{_cf('max-ttl-seconds')}", Input).value = "500"
            await pilot.pause()

            # Allowlist modes reveal their allowlist inputs.
            app.query_one(f"#input-{_cf('query-strings')}", Select).value = "allowlist"
            await pilot.pause()
            assert app.query_one(f"#field-{_cf('query-string-allowlist')}").display
            app.query_one(
                f"#input-{_cf('query-string-allowlist')}", Input
            ).value = "v, page"
            app.query_one(f"#input-{_cf('cookies')}", Select).value = "allowlist"
            await pilot.pause()
            app.query_one(
                f"#input-{_cf('cookie-allowlist')}", Input
            ).value = "session, csrftoken"
            app.query_one(
                f"#input-{_cf('forward-authorization-header')}", Checkbox
            ).value = True
            await pilot.pause()

            await _ctrl_s(app, pilot)

    _run(scenario())

    behavior = load_config(path).cloudfront.cached_behaviors[0]
    assert behavior.name == "assets"
    assert behavior.path_pattern == "/assets/*"
    assert behavior.compress is False
    assert behavior.cache_by_origin_headers is False
    assert behavior.min_ttl_seconds == 5
    assert behavior.default_ttl_seconds == 50
    assert behavior.max_ttl_seconds == 500
    assert behavior.query_strings.value == "allowlist"
    assert behavior.query_string_allowlist == ["v", "page"]
    assert behavior.cookies.value == "allowlist"
    assert behavior.cookie_allowlist == ["session", "csrftoken"]
    assert behavior.forward_authorization_header is True


def test_allowlist_hidden_until_mode_requires_it(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
            await pilot.pause()
            # Default query-string mode "all" hides the allowlist.
            assert (
                app.query_one(f"#field-{_cf('query-string-allowlist')}").display
                is False
            )
            app.query_one(
                f"#input-{_cf('query-strings')}", Select
            ).value = "allowlist"
            await pilot.pause()
            assert (
                app.query_one(f"#field-{_cf('query-string-allowlist')}").display
                is True
            )

    _run(scenario())


def test_switching_mode_away_from_allowlist_confirms_removal(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)  # behavior 0 uses allowlist modes

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            # Switch query strings away from allowlist -> confirm removal.
            app.query_one(f"#input-{_cf('query-strings')}", Select).value = "all"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-yes")
            await pilot.pause()

            # The hidden allowlist value is removed and its field hidden.
            assert (
                app._document.is_explicit(
                    "cloudfront.cached_behaviors[0].query_string_allowlist"
                )
                is False
            )
            assert (
                app.query_one(f"#field-{_cf('query-string-allowlist')}").display
                is False
            )

            await _ctrl_s(app, pilot)

    _run(scenario())

    behavior = load_config(path).cloudfront.cached_behaviors[0]
    assert behavior.query_strings.value == "all"
    assert behavior.query_string_allowlist == []
    # The cookie allowlist was untouched.
    assert behavior.cookie_allowlist == ["session"]


def test_cancel_mode_switch_preserves_hidden_allowlist(tmp_path: Path) -> None:
    path = _write(tmp_path, CF_CONFIGURED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one(f"#input-{_cf('query-strings')}", Select).value = "none"
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-no")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            # Cancelling keeps the allowlist values and returns to allowlist mode.
            # Read raw presence (never validating) since the confirm interval left
            # the draft transiently invalid before the mode was restored.
            assert (
                app._document.raw_value(
                    "cloudfront.cached_behaviors[0].query_strings"
                )
                == "allowlist"
            )
            assert app._document.raw_value(
                "cloudfront.cached_behaviors[0].query_string_allowlist"
            ) == ["v", "page"]

    _run(scenario())


# -- cross-field validation prevents save ------------------------------------


def test_invalid_ttl_order_prevents_save(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
            await pilot.pause()
            app.query_one(f"#input-{_cf('name')}", Input).value = "bad-ttl"
            app.query_one(f"#input-{_cf('path-pattern')}", Input).value = "/x/*"
            await pilot.pause()
            # default < min is invalid ordering.
            app.query_one(f"#input-{_cf('min-ttl-seconds')}", Input).value = "100"
            app.query_one(f"#input-{_cf('default-ttl-seconds')}", Input).value = "10"
            await pilot.pause()

            await _ctrl_s(app, pilot)
            # The behavior row is marked invalid and nothing is written.
            assert app.query_one("#section-error", Static).display is True
            assert load_config(path).cloudfront.enabled is False

    _run(scenario())


def test_duplicate_behavior_name_prevents_save(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()

            app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
            await pilot.pause()
            app.query_one("#input-cloudfront-cached-behaviors-0-name", Input).value = "dup"
            app.query_one(
                "#input-cloudfront-cached-behaviors-0-path-pattern", Input
            ).value = "/a/*"
            await pilot.pause()

            app.query_one("#nestedadd-cloudfront-cached-behaviors", Button).press()
            await pilot.pause()
            app.query_one("#input-cloudfront-cached-behaviors-1-name", Input).value = "dup"
            app.query_one(
                "#input-cloudfront-cached-behaviors-1-path-pattern", Input
            ).value = "/b/*"
            await pilot.pause()

            await _ctrl_s(app, pilot)
            assert load_config(path).cloudfront.enabled is False

    _run(scenario())


def test_custom_domain_without_certificate_prevents_save(tmp_path: Path) -> None:
    path = _write(tmp_path, ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            app.query_one("#advanced-cloudfront", Collapsible).collapsed = False
            await pilot.pause()
            app.query_one(
                "#input-cloudfront-custom-domain", Input
            ).value = "cdn.example.com"
            await pilot.pause()
            await _add_valid_behavior(app, pilot)

            await _ctrl_s(app, pilot)
            assert app.query_one("#error-cloudfront-custom-domain", Static).display is True
            assert load_config(path).cloudfront.enabled is False

    _run(scenario())


def test_enabling_cloudfront_without_domain_flags_domain(tmp_path: Path) -> None:
    # A project with services but no ALB domain: enabling CloudFront must point
    # the operator at the missing cluster domain.
    no_domain = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
"""
    path = _write(tmp_path, no_domain)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-cloudfront-enabled", Checkbox).value = True
            await pilot.pause()
            await _add_valid_behavior(app, pilot)
            await _ctrl_s(app, pilot)
            assert app.query_one("#error-alb-domain", Static).display is True
            assert load_config(path).cloudfront.enabled is False

    _run(scenario())
