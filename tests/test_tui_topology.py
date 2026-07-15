"""Review configuration topology (ticket 14).

Two layers are covered: the pure :func:`derive_topology` derivation over a
project document, and the Review section's rendering of that topology through
Textual Pilot — including collapse for a large fixture and navigation from a
dangling relationship to its owning editor.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Collapsible, Static

from darth_infra.config.document import ProjectDocument
from darth_infra.config.topology import (
    NODE_ALB,
    NODE_BUCKET,
    NODE_CLOUDFRONT,
    NODE_RDS,
    NODE_SECRET,
    NODE_SERVICE,
    derive_topology,
)
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.field_registry import Section


BASE = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod"]

[[services]]
name = "web"
port = 8000
cpu = 256

[[services]]
name = "worker"
cpu = 256

[[s3_buckets]]
name = "media"

[[s3_buckets.connections]]
service = "web"
env_key = "MEDIA_BUCKET"

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

[cloudfront]
enabled = true

[[cloudfront.cached_behaviors]]
name = "static"
path_pattern = "/static/*"
"""


def _write(tmp_path: Path, text: str = BASE) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


def test_derive_topology_nodes_and_edges(tmp_path: Path) -> None:
    doc = ProjectDocument.load(_write(tmp_path))
    topo = derive_topology(doc)

    kinds = {node.kind for node in topo.nodes}
    assert {
        NODE_SERVICE,
        NODE_BUCKET,
        NODE_SECRET,
        NODE_RDS,
        NODE_ALB,
        NODE_CLOUDFRONT,
    } <= kinds
    assert {node.name for node in topo.nodes_of(NODE_SERVICE)} == {"web", "worker"}

    # CloudFront sits in front of ALB, ALB routes to its default target, RDS is
    # exposed to a service, and the bucket connects to a service.
    pairs = {(e.source, e.target) for e in topo.edges}
    assert ("CloudFront", "ALB") in pairs
    assert ("ALB", "web") in pairs
    assert ("app", "web") in pairs
    assert ("media", "web") in pairs
    assert not topo.dangling_edges


def test_derive_topology_flags_dangling_reference(tmp_path: Path) -> None:
    text = BASE.replace('expose_to = ["web"]', 'expose_to = ["web", "ghost"]')
    doc = ProjectDocument.load(_write(tmp_path, text))
    topo = derive_topology(doc)

    dangling = topo.dangling_edges
    assert len(dangling) == 1
    edge = dangling[0]
    assert edge.target == "ghost"
    assert edge.owner_section == Section.DATABASE.value
    assert edge.owner_path == "rds.expose_to"


def test_review_topology_renders_and_identifies_as_configuration(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(_write(tmp_path)))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            topo = app.query_one("#review-topology")
            rendered = " ".join(str(s.render()) for s in topo.query(Static))
            # It shows configured routes/dependencies...
            assert "web" in rendered
            assert "ALB" in rendered
            # ...and clearly identifies itself as configuration, not AWS state.
            assert "not deployed AWS state" in rendered

    _run(scenario())


def test_review_topology_collapses_for_large_fixture(tmp_path: Path) -> None:
    lines = [
        "#:schema ./darth-infra.schema.json",
        "[project]",
        'name = "demo"',
        'aws_region = "us-east-1"',
        'vpc_name = "vpc-x"',
        'environments = ["prod"]',
        "",
    ]
    for i in range(14):
        lines += ["[[services]]", f'name = "svc{i}"', "port = 8000", "cpu = 256", ""]
    text = "\n".join(lines)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(_write(tmp_path, text)))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            topo = app.query_one("#review-topology")
            groups = topo.query(Collapsible)
            assert groups
            # A large topology starts collapsed so Review stays usable.
            assert any(group.collapsed for group in groups)

    _run(scenario())


def test_dangling_topology_relationship_navigates_to_owning_editor(
    tmp_path: Path,
) -> None:
    # A service granted access to a bucket that does not exist. The model permits
    # this (it does not validate s3_access), so the config still loads, but the
    # topology flags the relationship as dangling and links it to Services.
    text = BASE.replace(
        'name = "web"\nport = 8000\ncpu = 256',
        'name = "web"\nport = 8000\ncpu = 256\ns3_access = ["nope"]',
    )

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(_write(tmp_path, text)))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            topo = app.query_one("#review-topology")
            dangling = topo.query(".topology-dangling")
            assert dangling
            dangling.first().press()
            await pilot.pause()
            await pilot.pause()
            # It navigates to the owning editor (Services owns s3_access).
            assert app.current_section is Section.SERVICES

    _run(scenario())
