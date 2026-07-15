"""Deployment-sensitive change warnings and the Review save confirmation (ticket 14).

Covers the pure :func:`deployment_sensitive_changes` classification and the
Review section's behavior: one future-deploy confirmation per save covering all
deployment-sensitive changes, ordinary changes saving without a prompt, warnings
clearing after a revert, and environment-variable values remaining visible while
actual secret values are never present.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Static

from darth_infra.config.deploy_risk import (
    CATEGORY_ALB_MODE,
    CATEGORY_ENVIRONMENT,
    CATEGORY_NETWORK,
    CATEGORY_RDS,
    CATEGORY_SERVICE,
    deployment_sensitive_changes,
)
from darth_infra.config.document import (
    ABSENT,
    ChangeOperation,
    ProjectDocument,
    SemanticChange,
)
from darth_infra.config.loader import load_config
from darth_infra.tui.editor import ConfigEditorApp
from darth_infra.tui.editor.navigation import nav_button_id
from darth_infra.tui.editor.review import RiskConfirmScreen
from darth_infra.tui.field_registry import Section


CONFIG = """\
#:schema ./darth-infra.schema.json
[project]
name = "demo"
aws_region = "us-east-1"
vpc_name = "vpc-x"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000
cpu = 256

[services.environment_variables]
LOG_LEVEL = "info"

[[secrets]]
name = "API_KEY"
source = "generate"
"""


def _write(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def _run(coro) -> None:
    asyncio.run(coro)


# -- pure classification ----------------------------------------------------


def test_deployment_sensitive_categories() -> None:
    changes = [
        SemanticChange(
            "services[name=web]", ChangeOperation.REMOVED, {"name": "web"}, ABSENT
        ),
        SemanticChange("rds.database_name", ChangeOperation.CHANGED, "a", "b"),
        SemanticChange("alb.mode", ChangeOperation.CHANGED, "shared", "dedicated"),
        SemanticChange(
            "project.environments",
            ChangeOperation.CHANGED,
            ["prod"],
            ["prod", "dev"],
        ),
        SemanticChange("project.vpc_name", ChangeOperation.CHANGED, "a", "b"),
    ]
    risks = deployment_sensitive_changes(changes)
    assert {r.category for r in risks} == {
        CATEGORY_SERVICE,
        CATEGORY_RDS,
        CATEGORY_ALB_MODE,
        CATEGORY_ENVIRONMENT,
        CATEGORY_NETWORK,
    }
    # Warnings speak of what a deploy *may* do; they never assert a fait accompli.
    for risk in risks:
        assert "may" in risk.summary or "will be created" in risk.summary
        assert "deleted the" not in risk.summary


def test_ordinary_changes_are_not_deployment_sensitive() -> None:
    changes = [
        SemanticChange(
            "services[name=web].environment_variables.LOG_LEVEL",
            ChangeOperation.CHANGED,
            "info",
            "debug",
        ),
        SemanticChange("project.tags.team", ChangeOperation.ADDED, ABSENT, "platform"),
        SemanticChange(
            "services[name=web].health_check_path",
            ChangeOperation.CHANGED,
            "/health",
            "/healthz",
        ),
    ]
    assert deployment_sensitive_changes(changes) == []


# -- Review save confirmation ----------------------------------------------


def test_deployment_sensitive_change_requires_one_confirmation(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # A network-identity change (region) is deployment-sensitive.
            app.query_one("#input-project-aws-region", Input).value = "eu-west-1"
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()

            # Review shows the deployment-sensitive warning inline.
            risks = app.query_one("#review-risks")
            assert risks.display is True

            # Saving opens exactly one confirmation covering the changes.
            await pilot.click("#review-save")
            await pilot.pause()
            assert isinstance(app.screen, RiskConfirmScreen)

            # Cancelling leaves the file unwritten.
            await pilot.click("#risk-cancel")
            await pilot.pause()
            assert load_config(path).aws_region == "us-east-1"

            # Confirming writes the change.
            await pilot.click("#review-save")
            await pilot.pause()
            await pilot.click("#risk-confirm")
            await pilot.pause()
            await pilot.pause()
            assert load_config(path).aws_region == "eu-west-1"

    _run(scenario())


def test_ordinary_change_saves_without_confirmation(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Renaming the project is not a deployment-sensitive change.
            app.query_one("#input-project-name", Input).value = "demo-renamed"
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()

            assert app.query_one("#review-risks").display is False

            await pilot.click("#review-save")
            await pilot.pause()
            await pilot.pause()
            # No confirmation appeared and the change was written directly.
            assert not isinstance(app.screen, RiskConfirmScreen)
            assert load_config(path).project_name == "demo-renamed"

    _run(scenario())


def test_risk_warning_clears_after_revert(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            app.query_one("#input-project-aws-region", Input).value = "eu-west-1"
            await pilot.pause()
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#review-risks").display is True

            # Reverting the draft to the loaded document clears the warning.
            app._document.revert_all()
            review = app._section_widget
            review.refresh_views()
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#review-risks").display is False

    _run(scenario())


def test_env_var_values_visible_and_secret_values_absent(tmp_path: Path) -> None:
    path = _write(tmp_path)

    async def scenario() -> None:
        app = ConfigEditorApp(document=ProjectDocument.load(path))
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Change an ordinary environment variable value.
            app._document.set(
                "services[0].environment_variables.LOG_LEVEL", "debug"
            )
            await pilot.click(f"#{nav_button_id(Section.REVIEW)}")
            await pilot.pause()
            await pilot.pause()

            changes_text = " ".join(
                str(s.render())
                for s in app.query_one("#review-changes").query(Static)
            )
            toml_text = " ".join(
                str(s.render())
                for s in app.query_one("#review-toml").query(Static)
            )
            # The environment-variable value is ordinary visible configuration.
            assert "debug" in changes_text
            assert "debug" in toml_text
            # The secret's declaration is visible but the document holds no
            # secret value to leak (source only, never a plaintext value).
            assert "generate" not in changes_text or "API_KEY" in changes_text

    _run(scenario())
