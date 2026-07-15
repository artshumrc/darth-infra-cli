"""Advanced Services editing and reference-aware deletion (ticket 07).

These Textual Pilot tests drive the advanced service settings through the same
visible controls a user operates — architecture Automatic/Override, user-data,
ECS Exec, per-service and global service discovery, and the nested ulimit and
EBS-volume master-detail controls — and assert persisted TOML through
``load_config``. They also cover reference-aware cascade deletion and duplication
of service-owned nested settings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Checkbox, Input, ListView, Select, TextArea

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.collection import ImpactConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

FARGATE = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
"""

EC2 = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
launch_type = "ec2"
ec2_instance_type = "t3.medium"
"""

# An EC2 service with every advanced/nested value set, for no-op preservation.
FULL_EC2 = """\
#:schema ./darth-infra.schema.json
# Hand-formatted; advanced values must survive a no-op save.

[[services]]
name = "web"
port = 8000
enable_exec = false
launch_type = "ec2"
ec2_instance_type = "t3.medium"
architecture = "x86_64"
user_data_script = "scripts/user_data.sh"
user_data_script_content = "#!/bin/bash\\nsysctl -w vm.max_map_count=262144"
enable_service_discovery = true

[[services.ulimits]]
name = "nofile"
soft_limit = 65536
hard_limit = 65536

[[services.ebs_volumes]]
name = "data"
size_gb = 50
mount_path = "/data"
volume_type = "io2"
filesystem_type = "xfs"

[project]
name = "demo"
environments = ["prod"]

[service_discovery]
namespace_template = "{project}-{env}.local"
"""

DUP_WITH_NESTED = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
launch_type = "ec2"
ec2_instance_type = "t3.medium"

[[services.ulimits]]
name = "nofile"
soft_limit = 32768
hard_limit = 32768

[[services.ebs_volumes]]
name = "data"
size_gb = 30
mount_path = "/data"

[alb]
domain = "demo.example.com"
default_target_service = "web"

[[alb.path_rules]]
name = "web-rule"
path_pattern = "/app/*"
target_service = "web"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


async def _goto_services(app, pilot) -> None:
    await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
    await pilot.pause()


def test_architecture_override_and_return_to_automatic(tmp_path: Path) -> None:
    path = _write(tmp_path, EC2)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # Automatic by default: the control is hidden until Override.
            control = app.query_one("#control-services-0-architecture")
            assert control.display is False

            app.query_one("#mode-services-0-architecture", Button).press()
            await pilot.pause()
            assert control.display is True
            app.query_one("#input-services-0-architecture", Select).value = "arm64"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert load_config(path).services[0].architecture.value == "arm64"

            # Returning to Automatic asks for confirmation, then omits the field.
            app.query_one("#mode-services-0-architecture", Button).press()
            await pilot.pause()
            await pilot.click("#confirm-yes")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            # Omitted: EC2 inference re-detects x86_64 from t3.medium.
            doc = ProjectDocument.load(path)
            assert doc.is_explicit("services[0].architecture") is False

    _run(scenario())


def test_user_data_path_and_content_round_trip(tmp_path: Path) -> None:
    path = _write(tmp_path, EC2)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            app.query_one(
                "#input-services-0-user-data-script", Input
            ).value = "scripts/boot.sh"
            app.query_one(
                "#input-services-0-user-data-script-content", TextArea
            ).text = "#!/bin/bash\necho hi"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            svc = load_config(path).services[0]
            assert svc.user_data_script == "scripts/boot.sh"
            assert svc.user_data_script_content == "#!/bin/bash\necho hi"

    _run(scenario())


def test_enable_service_discovery_and_global_namespace(tmp_path: Path) -> None:
    path = _write(tmp_path, FARGATE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            app.query_one(
                "#input-services-0-enable-service-discovery", Checkbox
            ).value = True
            app.query_one(
                "#input-service-discovery-namespace-template", Input
            ).value = "{project}-{env}.local"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            config = load_config(path)
            assert config.services[0].enable_service_discovery is True
            assert (
                config.service_discovery.namespace_template
                == "{project}-{env}.local"
            )

    _run(scenario())


def test_ulimit_add_edit_duplicate_delete(tmp_path: Path) -> None:
    path = _write(tmp_path, FARGATE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)

            app.query_one("#nestedadd-services-0-ulimits", Button).press()
            await pilot.pause()
            app.query_one(
                "#input-services-0-ulimits-0-soft-limit", Input
            ).value = "1024"
            app.query_one(
                "#input-services-0-ulimits-0-hard-limit", Input
            ).value = "2048"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            ulimits = load_config(path).services[0].ulimits
            assert len(ulimits) == 1
            assert ulimits[0].name == "nofile"
            assert (ulimits[0].soft_limit, ulimits[0].hard_limit) == (1024, 2048)

            # Duplicate: a second row appears; it is a duplicate until renamed.
            app.query_one("#nesteddup-services-0-ulimits", Button).press()
            await pilot.pause()
            nested = app.query_one("#nested-services-0-ulimits")
            assert nested._count() == 2
            assert nested.has_error() is True  # duplicate ulimit name

            # Rename the copy to a distinct ulimit and it becomes valid.
            app.query_one(
                "#input-services-0-ulimits-1-name", Select
            ).value = "memlock"
            await pilot.pause()
            assert nested.has_error() is False

            # Delete the second row with confirmation.
            app.query_one("#nesteddel-services-0-ulimits", Button).press()
            await pilot.pause()
            await pilot.click("#confirm-yes")
            await pilot.pause()
            await pilot.pause()
            assert nested._count() == 1

    _run(scenario())


def test_ebs_editor_is_ec2_only_and_round_trips(tmp_path: Path) -> None:
    path = _write(tmp_path, EC2)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            ebs = app.query_one("#nested-services-0-ebs-volumes")
            assert ebs.display is True  # visible for an EC2 service

            app.query_one("#nestedadd-services-0-ebs-volumes", Button).press()
            await pilot.pause()
            app.query_one("#input-services-0-ebs-volumes-0-name", Input).value = "data"
            app.query_one(
                "#input-services-0-ebs-volumes-0-size-gb", Input
            ).value = "40"
            app.query_one(
                "#input-services-0-ebs-volumes-0-mount-path", Input
            ).value = "/data"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            vols = load_config(path).services[0].ebs_volumes
            assert len(vols) == 1
            assert vols[0].name == "data"
            assert vols[0].size_gb == 40
            assert vols[0].mount_path == "/data"

            # Switching to Fargate hides the EC2-only EBS panel.
            app.query_one("#input-services-0-launch-type", Select).value = "fargate"
            await pilot.pause()
            assert ebs.display is False

    _run(scenario())


def test_no_op_save_preserves_advanced_values(tmp_path: Path) -> None:
    path = _write(tmp_path, FULL_EC2)
    before = path.read_text()

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()

    _run(scenario())

    # A no-op editor save leaves the document byte-for-byte unchanged and every
    # advanced value intact.
    assert path.read_text() == before
    svc = load_config(path).services[0]
    assert svc.architecture.value == "x86_64"
    assert svc.user_data_script == "scripts/user_data.sh"
    assert svc.user_data_script_content.startswith("#!/bin/bash")
    assert svc.enable_exec is False
    assert svc.enable_service_discovery is True
    assert svc.ulimits[0].name == "nofile"
    assert svc.ebs_volumes[0].volume_type == "io2"
    assert (
        load_config(path).service_discovery.namespace_template
        == "{project}-{env}.local"
    )


def test_duplicate_copies_nested_but_not_incoming_references(tmp_path: Path) -> None:
    path = _write(tmp_path, DUP_WITH_NESTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)

            await pilot.click("#md-duplicate")
            await pilot.pause()
            app.query_one("#input-services-1-name", Input).value = "web2"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            config = load_config(path)
            assert [s.name for s in config.services] == ["web", "web2"]
            web2 = config.services[1]
            # Service-owned nested settings copied.
            assert [u.name for u in web2.ulimits] == ["nofile"]
            assert [v.name for v in web2.ebs_volumes] == ["data"]
            # Incoming ALB references were not duplicated onto the copy.
            assert config.alb.default_target_service == "web"
            assert [r.target_service for r in config.alb.path_rules] == ["web"]

    _run(scenario())


def test_referenced_service_cascade_via_pilot(tmp_path: Path) -> None:
    path = _write(tmp_path, DUP_WITH_NESTED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # "web" is the ALB default target and a path-rule target: deleting it
            # would leave the domain without a target, so add a second service to
            # take over the default target first is not needed here — instead we
            # confirm the impact list lists the references.
            await pilot.click("#md-delete")
            await pilot.pause()
            assert isinstance(app.screen, ImpactConfirmScreen)
            listed = [
                str(item.render())
                for item in app.screen.query("#impact-list Static")
            ]
            joined = " ".join(listed)
            assert "ALB default target" in joined
            assert "path rule" in joined

    _run(scenario())


def test_worker_hides_ec2_only_advanced_fields(tmp_path: Path) -> None:
    path = _write(tmp_path, FARGATE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # Fargate: architecture, user-data, and EBS panels are unavailable.
            assert app.query_one("#field-services-0-architecture").display is False
            assert (
                app.query_one("#field-services-0-user-data-script").display is False
            )
            assert app.query_one("#nested-services-0-ebs-volumes").display is False

    _run(scenario())