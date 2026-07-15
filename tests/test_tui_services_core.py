"""Master-detail Services editor for the Guided configuration editor (ticket 06).

These Textual Pilot tests drive the Services section through the same visible
controls a user operates: the searchable service list, the Add/Duplicate/Delete
actions, and the detail editor for the selected service. They assert persisted
TOML through ``load_config`` rather than inspecting private list-refresh state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Checkbox, Input, ListView, Select, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.collection import ConfirmScreen
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section

ONE_SERVICE = """\
#:schema ./darth-infra.schema.json
# A hand-formatted project. Comments and ordering must survive edits.

[project]
name = "demo"
aws_region = "us-east-1"
environments = ["prod"]

# The main web service
[[services]]
name = "web"
port = 8000
desired_count = 3
enable_exec = false
"""

TWO_SERVICES = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000

[[services]]
name = "worker"
"""

REFERENCED = """\
[project]
name = "demo"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
cpu = 512

[services.environment_variables]
FOO = "bar"

[alb]
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


async def _goto_services(app, pilot) -> None:
    await pilot.click(f"#{nav_button_id(Section.SERVICES)}")
    await pilot.pause()


async def _select_row(app, pilot, row: int) -> None:
    lv = app.query_one("#md-list", ListView)
    app.set_focus(lv)
    lv.index = row
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


def _capture_notices(app) -> list[str]:
    notices: list[str] = []

    def _cap(message="", **_kwargs) -> None:
        notices.append(str(message))

    app.notify = _cap  # type: ignore[assignment]
    return notices


def test_add_service_creates_draft_requiring_unique_name(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            section = app._section_widget
            assert section.item_count() == 1

            await pilot.click("#md-add")
            await pilot.pause()
            # A new draft service exists and is selected with an empty name.
            assert section.item_count() == 2
            assert app.query_one("#input-services-1-name", Input).value == ""

            # It is invalid until named, so Ctrl+S refuses to save.
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.query_one("#error-services-1-name", Static).display is True
            # Nothing was written: the file still holds a single service.
            assert len(load_config(path).services) == 1

            # Naming it uniquely makes the save succeed.
            app.query_one("#input-services-1-name", Input).value = "worker"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert [s.name for s in load_config(path).services] == ["web", "worker"]

    _run(scenario())


def test_search_filters_the_service_list(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            section = app._section_widget
            assert len(section._visible) == 2

            app.query_one("#md-search", Input).value = "work"
            await pilot.pause()
            assert section._visible == [1]

            app.query_one("#md-search", Input).value = ""
            await pilot.pause()
            assert len(section._visible) == 2

    _run(scenario())


def test_select_switches_detail_and_keeps_edits(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # Edit the first service, then switch to the second and back.
            app.query_one("#input-services-0-cpu", Input).value = "1024"
            await pilot.pause()
            await _select_row(app, pilot, 1)
            assert app.query_one("#input-services-1-name", Input).value == "worker"
            await _select_row(app, pilot, 0)
            # The earlier edit was committed to the draft, not lost.
            assert app.query_one("#input-services-0-cpu", Input).value == "1024"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert load_config(path).services[0].cpu == 1024

    _run(scenario())


def test_every_common_field_saves_and_reloads(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)

            def _set(field: str, value: str) -> None:
                slug = field.replace("_", "-")
                app.query_one(f"#input-services-0-{slug}", Input).value = value

            _set("name", "api")
            _set("dockerfile", "Dockerfile.prod")
            _set("port", "9000")
            _set("health_check_path", "/healthz")
            _set("cpu", "512")
            _set("memory_mib", "1024")
            _set("desired_count", "4")
            _set("build_context", "svc")
            _set("docker_build_target", "runtime")
            _set("health_check_http_codes", "200")
            _set("health_check_timeout_seconds", "7")
            _set("health_check_interval_seconds", "45")
            _set("healthy_threshold_count", "3")
            _set("unhealthy_threshold_count", "4")
            _set("health_check_grace_period_seconds", "60")
            _set("command", "gunicorn app.wsgi")
            await pilot.pause()
            app.query_one("#input-services-0-enable-exec", Checkbox).value = True
            app.query_one(
                "#input-services-0-enable-ses-send-email", Checkbox
            ).value = True
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

            svc = load_config(path).services[0]
            assert svc.name == "api"
            assert svc.dockerfile == "Dockerfile.prod"
            assert svc.port == 9000
            assert svc.health_check_path == "/healthz"
            assert svc.cpu == 512
            assert svc.memory_mib == 1024
            assert svc.desired_count == 4
            assert svc.build_context == "svc"
            assert svc.docker_build_target == "runtime"
            assert svc.health_check_http_codes == "200"
            assert svc.health_check_timeout_seconds == 7
            assert svc.health_check_interval_seconds == 45
            assert svc.healthy_threshold_count == 3
            assert svc.unhealthy_threshold_count == 4
            assert svc.health_check_grace_period_seconds == 60
            assert svc.command == "gunicorn app.wsgi"
            assert svc.enable_exec is True
            assert svc.enable_ses_send_email is True

    _run(scenario())


def test_launch_type_ec2_saves_instance_type(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            app.query_one("#input-services-0-launch-type", Select).value = "ec2"
            await pilot.pause()
            # The EC2 instance type field becomes visible once EC2 is chosen.
            ec2_field = app.query_one("#field-services-0-ec2-instance-type")
            assert ec2_field.display is True
            app.query_one(
                "#input-services-0-ec2-instance-type", Input
            ).value = "t3.medium"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            svc = load_config(path).services[0]
            assert svc.launch_type.value == "ec2"
            assert svc.ec2_instance_type == "t3.medium"

    _run(scenario())


def test_desired_count_and_ecs_exec_round_trip(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # Edit only the name; the explicit non-default desired_count (3) and
            # enable_exec (false) must survive rather than revert to defaults.
            app.query_one("#input-services-0-name", Input).value = "renamed"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            svc = load_config(path).services[0]
            assert svc.name == "renamed"
            assert svc.desired_count == 3
            assert svc.enable_exec is False

    _run(scenario())


def test_duplicate_copies_fields_but_no_incoming_references(tmp_path: Path) -> None:
    path = _write(tmp_path, REFERENCED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)

            await pilot.click("#md-duplicate")
            await pilot.pause()
            section = app._section_widget
            assert section.item_count() == 2
            # The duplicate copied service-owned fields but starts unnamed and
            # therefore invalid.
            assert app.query_one("#input-services-1-name", Input).value == ""
            assert app.query_one("#input-services-1-cpu", Input).value == "512"

            await pilot.press("ctrl+s")
            await pilot.pause()
            # Still one service on disk: the invalid duplicate blocked the save.
            assert len(load_config(path).services) == 1

            app.query_one("#input-services-1-name", Input).value = "web2"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            config = load_config(path)
            assert [s.name for s in config.services] == ["web", "web2"]
            web2 = config.services[1]
            assert web2.cpu == 512
            assert web2.environment_variables == {"FOO": "bar"}
            # The incoming ALB reference was not duplicated onto the copy.
            assert config.alb.default_target_service == "web"

    _run(scenario())


def test_referenced_service_delete_is_blocked(tmp_path: Path) -> None:
    path = _write(tmp_path, REFERENCED)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            notices = _capture_notices(app)

            await pilot.click("#md-delete")
            await pilot.pause()
            # No confirmation dialog opened; an actionable message explains why.
            assert not isinstance(app.screen, ConfirmScreen)
            assert any("Cannot delete" in n and "ALB" in n for n in notices)
            # The service and its reference are intact — no dangling reference.
            config = load_config(path)
            assert [s.name for s in config.services] == ["web"]
            assert config.alb.default_target_service == "web"

    _run(scenario())


def test_unreferenced_service_delete_after_confirmation(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            await _select_row(app, pilot, 1)  # the unreferenced "worker"

            await pilot.click("#md-delete")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm-yes")
            await pilot.pause()
            await pilot.pause()

            section = app._section_widget
            assert section.item_count() == 1
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert [s.name for s in load_config(path).services] == ["web"]

    _run(scenario())


def test_environment_variables_are_visible_and_persist(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            slug = "services-0-environment-variables"
            app.query_one(f"#kvkey-{slug}", Input).value = "LOG_LEVEL"
            app.query_one(f"#kvval-{slug}", Input).value = "info"
            app.query_one(f"#kvadd-{slug}", Button).press()
            await pilot.pause()
            # The name and value are shown in plain text (not masked).
            list_view = app.query_one(f"#list-{slug}", ListView)
            rows = [_rendered(s) for s in list_view.query(Static)]
            assert any("LOG_LEVEL = info" in row for row in rows)

            await pilot.press("ctrl+s")
            await pilot.pause()
            assert load_config(path).services[0].environment_variables == {
                "LOG_LEVEL": "info"
            }

    _run(scenario())


def test_worker_hides_health_and_external_image_hides_build(tmp_path: Path) -> None:
    path = _write(tmp_path, ONE_SERVICE)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # Clearing the port turns the service into a worker: health-check
            # fields disappear without changing schema semantics.
            assert app.query_one("#field-services-0-health-check-path").display is True
            app.query_one("#input-services-0-port", Input).value = ""
            await pilot.pause()
            assert app.query_one("#field-services-0-health-check-path").display is False

            # Providing an external image hides the Docker build fields.
            assert app.query_one("#field-services-0-dockerfile").display is True
            app.query_one("#input-services-0-image", Input).value = "redis:7-alpine"
            await pilot.pause()
            assert app.query_one("#field-services-0-dockerfile").display is False

    _run(scenario())


def test_master_detail_keyboard_operable_at_both_sizes(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_SERVICES)

    async def scenario(size: tuple[int, int]) -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await _goto_services(app, pilot)
            # The list, search, actions, and detail name input are all reachable.
            for selector in ("#md-search", "#md-add", "#md-list"):
                assert app.query_one(selector).display is True
            name = app.query_one("#input-services-0-name", Input)
            assert name.display is True
            app.set_focus(name)
            await pilot.pause()
            assert app.focused is name

    _run(scenario((120, 35)))
    _run(scenario((80, 24)))
