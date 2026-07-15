"""Network-section behavior for the Guided configuration editor (ticket 05).

These Textual Pilot tests drive the Network section through its visible controls
against a deterministic fake AWS discovery adapter. They cover shared/dedicated
round-tripping, offline editing, the four discovery states (loading, results,
empty, failure), manual entry that discovery never overwrites, parent-scoped
dependent lookups, Automatic/Override with confirmed reset, and user-triggered
verification that never blocks a save.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.widgets import Button, Collapsible, Input, Select, Static

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
from darth_infra.tui.editor.collection import ConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

SHARED = """\
#:schema ./darth-infra.schema.json
# Network round-trip must not change mode or lose fields.

[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "artshumrc-prod-standard"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
cpu = 256

# Shared ALB identity
[alb]
mode = "shared"
shared_alb_name = "prod-shared-alb"
"""

DEDICATED = """\
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "prod-vpc"
vpc_id = "vpc-0abc1234def567890"
private_subnet_ids = ["subnet-0aaa", "subnet-0bbb"]
environments = ["prod"]

[[services]]
name = "web"
port = 8000
cpu = 256

[alb]
mode = "dedicated"
certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"
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


async def _goto_network(app: ConfigEditorApp, pilot) -> None:
    await pilot.pause()
    await pilot.click(f"#{nav_button_id(Section.NETWORK)}")
    await pilot.pause()


async def _expand_advanced(app) -> None:
    app.query_one("#advanced-network", Collapsible).collapsed = False


# -- round-tripping ----------------------------------------------------------


def test_shared_project_round_trips_without_mode_conversion(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#input-project-vpc-name", Input).value = "renamed-vpc"
            await pilot.pause()
            await _ctrl_s(app, pilot)

    _run(scenario())

    reloaded = load_config(path)
    assert reloaded.alb.mode.value == "shared"
    assert reloaded.alb.shared_alb_name == "prod-shared-alb"
    assert reloaded.vpc_name == "renamed-vpc"


def test_dedicated_project_round_trips_without_field_loss(tmp_path: Path) -> None:
    path = _write(tmp_path, DEDICATED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            # A dedicated project opens with its certificate visible and shared-
            # only selectors hidden; editing an unrelated field must not convert
            # it or drop the dedicated settings.
            app.query_one("#input-project-vpc-name", Input).value = "prod-vpc-2"
            await pilot.pause()
            await _ctrl_s(app, pilot)

    _run(scenario())

    reloaded = load_config(path)
    assert reloaded.alb.mode.value == "dedicated"
    assert reloaded.alb.certificate_arn == (
        "arn:aws:acm:us-east-1:123456789012:certificate/abcd-ef01"
    )
    assert reloaded.vpc_id == "vpc-0abc1234def567890"
    assert reloaded.private_subnet_ids == ["subnet-0aaa", "subnet-0bbb"]
    assert reloaded.vpc_name == "prod-vpc-2"


def test_dedicated_hides_shared_selector_and_shows_certificate(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, DEDICATED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            await _expand_advanced(app)
            await pilot.pause()
            assert app.query_one("#field-alb-shared-alb-name").display is False
            assert app.query_one("#field-alb-certificate-arn").display is True

    _run(scenario())


# -- offline editing ---------------------------------------------------------


def test_offline_adapter_still_saves(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)

    async def scenario() -> None:
        # The default adapter has no AWS access; local editing and saving must
        # still work end to end.
        app = ConfigEditorApp(
            document=ProjectDocument.load(path), discovery=OfflineAwsDiscovery()
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#input-project-vpc-name", Input).value = "offline-vpc"
            await pilot.pause()
            await _ctrl_s(app, pilot)

    _run(scenario())

    assert load_config(path).vpc_name == "offline-vpc"


# -- discovery states --------------------------------------------------------


def test_discovery_shows_loading_then_results(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    release = threading.Event()
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.VPC_NAME: DiscoveryResult.of(
                [ResourceRecord("prod-vpc", "prod-vpc (vpc-1)", {"vpc_id": "vpc-1"})]
            )
        },
        gate=lambda: release.wait(5),
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#discover-project-vpc-name", Button).press()
            await pilot.pause()
            status = app.query_one("#discstatus-project-vpc-name", Static)
            assert "loading" in _rendered(status).lower()

            release.set()
            await pilot.pause()
            await pilot.pause()
            assert "found" in _rendered(status).lower()
            select = app.query_one("#select-project-vpc-name", Select)
            assert any(
                value == "prod-vpc" for _, value in select._options  # noqa: SLF001
            ) or select.value == "prod-vpc" or "prod-vpc" in str(select._options)

    _run(scenario())


def test_discovery_empty_state_is_distinct(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        results={DiscoveryKind.VPC_NAME: DiscoveryResult.of([])}
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#discover-project-vpc-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#discstatus-project-vpc-name", Static)
            assert "no matching" in _rendered(status).lower()

    _run(scenario())


def test_discovery_failure_state_and_save_still_works(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        results={DiscoveryKind.VPC_NAME: DiscoveryResult.failed("no creds")}
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#discover-project-vpc-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#discstatus-project-vpc-name", Static)
            assert "failed" in _rendered(status).lower()

            # A failed lookup does not block a locally valid save.
            app.query_one("#input-project-vpc-name", Input).value = "typed-vpc"
            await pilot.pause()
            await _ctrl_s(app, pilot)

    _run(scenario())

    assert load_config(path).vpc_name == "typed-vpc"


def test_discovery_does_not_replace_a_manual_value(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.VPC_NAME: DiscoveryResult.of(
                [ResourceRecord("discovered-vpc", "discovered-vpc (vpc-9)")]
            )
        }
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            manual = app.query_one("#input-project-vpc-name", Input)
            manual.value = "hand-typed-vpc"
            await pilot.pause()
            app.query_one("#discover-project-vpc-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            # Discovery populated the picker but left the typed value untouched.
            assert manual.value == "hand-typed-vpc"

    _run(scenario())


# -- parent-scoped dependent lookups -----------------------------------------


def test_vpc_choice_scopes_subnet_discovery(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.PRIVATE_SUBNETS: DiscoveryResult.of(
                [ResourceRecord("subnet-a", "private-a (subnet-a)")]
            )
        }
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#input-project-vpc-name", Input).value = "chosen-vpc"
            await pilot.pause()
            await _expand_advanced(app)
            # Subnet override must be enabled to discover into it.
            app.query_one("#mode-project-private-subnet-ids", Button).press()
            await pilot.pause()
            app.query_one("#discover-project-private-subnet-ids", Button).press()
            await pilot.pause()
            await pilot.pause()

            last = fake.requests[-1]
            assert last.kind is DiscoveryKind.PRIVATE_SUBNETS
            assert last.vpc_name == "chosen-vpc"

    _run(scenario())


def test_alb_choice_scopes_listener_discovery(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.LOAD_BALANCER: DiscoveryResult.of(
                [
                    ResourceRecord(
                        "prod-shared-alb",
                        "prod-shared-alb (internet-facing)",
                        {"arn": "arn:alb:1"},
                    )
                ]
            ),
            DiscoveryKind.LISTENER: DiscoveryResult.of(
                [ResourceRecord("arn:listener:443", "HTTPS:443")]
            ),
        }
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#discover-alb-shared-alb-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            # Choosing the discovered ALB captures its ARN for dependent lookups.
            app.query_one("#select-alb-shared-alb-name", Select).value = (
                "prod-shared-alb"
            )
            await pilot.pause()

            await _expand_advanced(app)
            app.query_one("#mode-alb-shared-listener-arn", Button).press()
            await pilot.pause()
            app.query_one("#discover-alb-shared-listener-arn", Button).press()
            await pilot.pause()
            await pilot.pause()

            listener_requests = [
                r for r in fake.requests if r.kind is DiscoveryKind.LISTENER
            ]
            assert listener_requests
            assert listener_requests[-1].load_balancer_arn == "arn:alb:1"

    _run(scenario())


# -- Automatic/Override ------------------------------------------------------


def test_explicit_override_loads_in_override_mode(tmp_path: Path) -> None:
    path = _write(tmp_path, DEDICATED)  # has explicit vpc_id

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            await _expand_advanced(app)
            await pilot.pause()
            control = app.query_one("#control-project-vpc-id")
            assert control.display is True  # Override, not Automatic
            badge = app.query_one("#badge-project-vpc-id", Static)
            assert "SET" in _rendered(badge)

    _run(scenario())


def test_return_to_automatic_requires_confirmation_and_removes_key(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, DEDICATED)  # explicit vpc_id

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            await _expand_advanced(app)
            app.query_one("#mode-project-vpc-id", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#confirm-yes")
            await pilot.pause()
            assert app._document.is_explicit("project.vpc_id") is False

            await _ctrl_s(app, pilot)

    _run(scenario())

    reloaded = load_config(path)
    assert reloaded.vpc_id is None  # key was removed, back to Automatic


def test_cancel_return_to_automatic_keeps_the_value(tmp_path: Path) -> None:
    path = _write(tmp_path, DEDICATED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            await _expand_advanced(app)
            app.query_one("#mode-project-vpc-id", Button).press()
            await pilot.pause()
            await pilot.click("#confirm-no")
            await pilot.pause()
            assert app._document.is_explicit("project.vpc_id") is True

    _run(scenario())


# -- verification ------------------------------------------------------------


def test_verification_reports_verified(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(
        known={DiscoveryKind.VPC_NAME: {"artshumrc-prod-standard"}}
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#verify-project-vpc-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#verifystatus-project-vpc-name", Static)
            assert "verified" in _rendered(status).lower()

    _run(scenario())


def test_failed_verification_is_visible_and_does_not_block_save(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, SHARED)
    fake = FakeAwsDiscovery(known={DiscoveryKind.VPC_NAME: set()})  # nothing exists

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path), discovery=fake)
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            app.query_one("#verify-project-vpc-name", Button).press()
            await pilot.pause()
            await pilot.pause()
            status = app.query_one("#verifystatus-project-vpc-name", Static)
            assert "failed" in _rendered(status).lower()

            # A failed check does not block a locally valid save.
            await _ctrl_s(app, pilot)

    _run(scenario())

    # The document still saved (it is valid); mode preserved.
    assert load_config(path).alb.mode.value == "shared"


def test_verify_status_starts_not_checked(tmp_path: Path) -> None:
    path = _write(tmp_path, SHARED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await _goto_network(app, pilot)
            status = app.query_one("#verifystatus-project-vpc-name", Static)
            assert "not checked" in _rendered(status).lower()

    _run(scenario())


# -- no listener-priority allocation -----------------------------------------


def test_network_section_introduces_no_listener_priority_lookup() -> None:
    # Priorities are owned by Routing and deploy-time resolution; the Network
    # section and its adapter must not look up or allocate a listener priority.
    from darth_infra.tui.editor import aws_discovery as adapter_module
    from darth_infra.tui.editor import network as network_module
    from darth_infra.tui.editor.aws_discovery import DiscoveryKind

    # No discovery/verification kind is about listener priorities.
    assert not any("priorit" in kind.value for kind in DiscoveryKind)

    for module in (network_module, adapter_module):
        lowered = Path(module.__file__).read_text().lower()
        # No rule-priority lookup or allocation code (checked via code tokens
        # that would only appear in real priority-resolution logic).
        assert "describe_rules" not in lowered
        assert "listener_priority" not in lowered
        assert "default_listener_priority" not in lowered
        assert "path_rules" not in lowered
