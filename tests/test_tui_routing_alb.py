"""ALB routing-section behavior for the Guided editor (ticket 08).

These Textual Pilot tests drive the Routing section through its visible controls:
the cluster domain, default target service, the Automatic/Override default rule
priority, and the master-detail list of path rules. They assert persisted TOML
through ``load_config`` and the document's semantic diff, never private widget
state.

Routing owns only *preferred* listener-priority overrides; deploy-time allocation
stays authoritative. Nothing here queries or allocates a "next" priority — a
guard test proves the editor introduces no priority lookup or allocator.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Collapsible, Input, Select, Static

from darth_infra.config.document import ChangeOperation, ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.collection import ConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

# Two services, both with a container port (both eligible routing targets), and
# no ALB routing yet.
TWO_SERVICES = """\
#:schema ./darth-infra.schema.json
# A hand-formatted project. Comments and ordering must survive edits.

[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "kibana"
port = 5601
"""

# A shared-ALB project with complete routing already configured.
SHARED_ROUTED = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "kibana"
port = 5601

[alb]
mode = "shared"
shared_alb_name = "prod-shared-alb"
domain = "demo.example.com"
default_target_service = "web"
default_listener_priority = 100

[[alb.path_rules]]
name = "kibana-rule"
path_pattern = "/kibana/*"
target_service = "kibana"
priority = 200
"""

# A dedicated-ALB project with routing configured.
DEDICATED_ROUTED = """\
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


def _rendered(widget) -> str:
    return str(widget.render())


async def _goto_routing(app, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.ROUTING)}")
    await pilot.pause()


async def _expand_advanced(app) -> None:
    app.query_one("#advanced-routing", Collapsible).collapsed = False


# -- round-tripping ----------------------------------------------------------


def test_edits_and_round_trips_domain_target_priority_and_path_rules(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)

            app.query_one("#input-alb-domain", Input).value = "app.example.com"
            await pilot.pause()
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()

            # Override the default rule priority.
            await _expand_advanced(app)
            await pilot.pause()
            app.query_one("#mode-alb-default-listener-priority", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-default-listener-priority", Input
            ).value = "100"
            await pilot.pause()

            # Add a complete path rule with its own preferred priority.
            app.query_one("#nestedadd-alb-path-rules", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-name", Input
            ).value = "kibana-rule"
            app.query_one(
                "#input-alb-path-rules-0-path-pattern", Input
            ).value = "/kibana/*"
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-target-service", Select
            ).value = "kibana"
            await pilot.pause()
            app.query_one("#mode-alb-path-rules-0-priority", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-priority", Input
            ).value = "200"
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    cfg = load_config(path)
    assert cfg.alb.domain == "app.example.com"
    assert cfg.alb.default_target_service == "web"
    assert cfg.alb.default_listener_priority == 100
    assert len(cfg.alb.path_rules) == 1
    rule = cfg.alb.path_rules[0]
    assert rule.name == "kibana-rule"
    assert rule.path_pattern == "/kibana/*"
    assert rule.target_service == "kibana"
    assert rule.priority == 200


# -- Automatic / Override priorities -----------------------------------------


def test_automatic_priority_omits_the_toml_key(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-alb-domain", Input).value = "app.example.com"
            await pilot.pause()
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()
            # A path rule left on Automatic priority.
            app.query_one("#nestedadd-alb-path-rules", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-name", Input
            ).value = "kibana-rule"
            app.query_one(
                "#input-alb-path-rules-0-path-pattern", Input
            ).value = "/kibana/*"
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-target-service", Select
            ).value = "kibana"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    cfg = load_config(path)
    assert cfg.alb.default_listener_priority is None
    assert cfg.alb.path_rules[0].priority is None
    # Automatic omits the keys from the written document entirely.
    text = path.read_text()
    assert "default_listener_priority" not in text
    assert "priority" not in text


def test_override_priority_persists_validated_value(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-alb-domain", Input).value = "app.example.com"
            await pilot.pause()
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()
            await _expand_advanced(app)
            app.query_one("#mode-alb-default-listener-priority", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-default-listener-priority", Input
            ).value = "4321"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).alb.default_listener_priority == 4321


def test_return_to_automatic_requires_confirmation_and_reset_diff(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, SHARED_ROUTED)  # explicit default_listener_priority

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await _expand_advanced(app)
            await pilot.pause()
            # Explicit values load in Override mode (control visible).
            assert (
                app.query_one("#control-alb-default-listener-priority").display
                is True
            )

            app.query_one("#mode-alb-default-listener-priority", Button).press()
            await pilot.pause()
            # Returning an existing explicit value to Automatic asks first.
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-yes")
            await pilot.pause()

            assert (
                app._document.is_explicit("alb.default_listener_priority") is False
            )
            # The pending change is a reset-to-default, not a value change.
            resets = [
                c
                for c in app._document.semantic_changes()
                if "default_listener_priority" in c.path
            ]
            assert resets
            assert resets[0].operation is ChangeOperation.RESET_TO_DEFAULT

            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert load_config(path).alb.default_listener_priority is None


def test_cancel_return_to_automatic_keeps_the_value(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED_ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await _expand_advanced(app)
            app.query_one("#mode-alb-default-listener-priority", Button).press()
            await pilot.pause()
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert (
                app._document.is_explicit("alb.default_listener_priority") is True
            )

    _run(scenario())


# -- no priority allocator ---------------------------------------------------


def test_routing_editor_introduces_no_priority_allocator() -> None:
    # Priorities are preferred overrides only; deploy-time allocation stays
    # authoritative. The routing editor must not look up or allocate one.
    from darth_infra.tui.editor import routing as routing_module
    from darth_infra.tui.editor.aws_discovery import DiscoveryKind

    assert not any("priorit" in kind.value for kind in DiscoveryKind)

    # Guard against a boto rule lookup or a local "next priority" allocator.
    # (The word "allocate" legitimately appears in help text describing that
    # *deployment* allocates priorities, so it is not a useful signal.)
    lowered = Path(routing_module.__file__).read_text().lower()
    assert "describe_rules" not in lowered
    assert "next available" not in lowered
    assert "next_priority" not in lowered
    assert "get_next" not in lowered
    assert "boto" not in lowered


def test_no_priority_fetch_button_is_reachable(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED_ROUTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await _expand_advanced(app)
            await pilot.pause()
            labels = [
                _rendered(button).lower() for button in app.query(Button)
            ]
            assert not any("priority" in label for label in labels)
            assert not any("next available" in label for label in labels)

    _run(scenario())


# -- shared/dedicated no-op save ---------------------------------------------


def test_shared_configuration_survives_noop_save_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED_ROUTED)
    before = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert path.read_text() == before
    cfg = load_config(path)
    assert cfg.alb.mode.value == "shared"
    assert cfg.alb.shared_alb_name == "prod-shared-alb"
    assert cfg.alb.default_listener_priority == 100
    assert cfg.alb.path_rules[0].priority == 200


def test_dedicated_configuration_survives_noop_save_unchanged(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, DEDICATED_ROUTED)
    before = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    assert path.read_text() == before
    cfg = load_config(path)
    assert cfg.alb.mode.value == "dedicated"
    assert cfg.alb.certificate_arn == (
        "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"
    )


# -- validation: prevent save and focus --------------------------------------


def test_missing_domain_prevents_save_and_focuses_domain(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            # A target with no domain is invalid.
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert app.query_one("#error-alb-domain", Static).display is True
            assert app.focused is app.query_one("#input-alb-domain", Input)
            # Nothing written: the file still has no routing.
            assert load_config(path).alb.domain is None

    _run(scenario())


def test_duplicate_priority_prevents_save(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-alb-domain", Input).value = "app.example.com"
            await pilot.pause()
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()
            await _expand_advanced(app)
            app.query_one("#mode-alb-default-listener-priority", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-default-listener-priority", Input
            ).value = "100"
            await pilot.pause()

            # A path rule that reuses the default's priority (100) collides.
            app.query_one("#nestedadd-alb-path-rules", Button).press()
            await pilot.pause()
            app.query_one("#input-alb-path-rules-0-name", Input).value = "r1"
            app.query_one(
                "#input-alb-path-rules-0-path-pattern", Input
            ).value = "/r1/*"
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-target-service", Select
            ).value = "kibana"
            await pilot.pause()
            app.query_one("#mode-alb-path-rules-0-priority", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-priority", Input
            ).value = "100"
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()
            # The collision blocks the save: no path rule is written.
            assert load_config(path).alb.path_rules == []

    _run(scenario())


def test_colliding_rule_identities_prevent_save(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            app.query_one("#input-alb-domain", Input).value = "app.example.com"
            await pilot.pause()
            app.query_one(
                "#input-alb-default-target-service", Select
            ).value = "web"
            await pilot.pause()

            # Two rules whose names normalize to the same parameter key.
            app.query_one("#nestedadd-alb-path-rules", Button).press()
            await pilot.pause()
            app.query_one("#input-alb-path-rules-0-name", Input).value = "api-v1"
            app.query_one(
                "#input-alb-path-rules-0-path-pattern", Input
            ).value = "/a/*"
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-0-target-service", Select
            ).value = "kibana"
            await pilot.pause()

            app.query_one("#nestedadd-alb-path-rules", Button).press()
            await pilot.pause()
            app.query_one("#input-alb-path-rules-1-name", Input).value = "apiv1"
            app.query_one(
                "#input-alb-path-rules-1-path-pattern", Input
            ).value = "/b/*"
            await pilot.pause()
            app.query_one(
                "#input-alb-path-rules-1-target-service", Select
            ).value = "kibana"
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()
            # The normalized-name collision blocks the save.
            assert load_config(path).alb.path_rules == []

    _run(scenario())


def test_path_rule_target_lists_only_eligible_services(tmp_path: Path) -> None:
    # A worker service (no port) is not an eligible routing target.
    worker = TWO_SERVICES + '\n[[services]]\nname = "worker"\n'
    path = _write(tmp_path, worker)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_routing(app, pilot)
            # Default target options exclude the port-less worker.
            select = app.query_one("#input-alb-default-target-service", Select)
            values = [value for _label, value in select._options]  # noqa: SLF001
            assert "web" in values
            assert "kibana" in values
            assert "worker" not in values

    _run(scenario())
