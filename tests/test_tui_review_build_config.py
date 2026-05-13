from __future__ import annotations

from darth_infra.config.models import (
    EnvironmentOverride,
    ProjectConfig,
    SecretConfig,
    ServiceConfig,
)
from darth_infra.tui.screens.existing_resources import should_auto_fetch_saved_alb
from darth_infra.tui.screens.review import build_config_from_state
from darth_infra.tui.screens.services import merge_service_state
from darth_infra.tui.steps import STEP_ORDER
from darth_infra.tui.wizard_export import project_config_to_wizard_state


def test_build_config_from_state_preserves_service_ses_toggle() -> None:
    config = build_config_from_state(
        {
            "project_name": "demo",
            "aws_region": "us-east-1",
            "vpc_name": "demo-vpc",
            "vpc_id": None,
            "private_subnet_ids": [],
            "public_subnet_ids": [],
            "environments": ["prod"],
            "services": [
                {
                    "name": "web",
                    "port": 8000,
                    "enable_ses_send_email": True,
                },
                {
                    "name": "worker",
                    "port": None,
                    "enable_ses_send_email": False,
                },
            ],
        }
    )

    assert config.services[0].enable_ses_send_email is True
    assert config.services[1].enable_ses_send_email is False


def test_roundtrip_preserves_existing_service_secret_bindings() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(name="web", secrets=["DJANGO_SECRET_KEY", "SHARED_TOKEN"]),
            ServiceConfig(name="worker", port=None, secrets=["SHARED_TOKEN"]),
        ],
        secrets=[
            SecretConfig(name="DJANGO_SECRET_KEY"),
            SecretConfig(name="SHARED_TOKEN"),
        ],
    )

    state = project_config_to_wizard_state(config)

    assert {
        secret["name"]: secret.get("expose_to", []) for secret in state["secrets"]
    } == {
        "DJANGO_SECRET_KEY": ["web"],
        "SHARED_TOKEN": ["web", "worker"],
    }

    rebuilt = build_config_from_state(state)

    assert {service.name: service.secrets for service in rebuilt.services} == {
        "web": ["DJANGO_SECRET_KEY", "SHARED_TOKEN"],
        "worker": ["SHARED_TOKEN"],
    }


def test_merge_service_state_preserves_non_form_fields() -> None:
    existing = {
        "name": "web",
        "dockerfile": "Dockerfile",
        "secrets": ["DJANGO_SECRET_KEY"],
        "desired_count": 3,
    }

    edited = {
        "name": "web",
        "dockerfile": "Dockerfile.prod",
        "port": 8080,
    }

    merged = merge_service_state(existing, edited)

    assert merged == {
        "name": "web",
        "dockerfile": "Dockerfile.prod",
        "secrets": ["DJANGO_SECRET_KEY"],
        "desired_count": 3,
        "port": 8080,
    }


def test_roundtrip_preserves_project_and_environment_tags() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        tags={"owner": "platform"},
        environment_overrides={
            "prod": EnvironmentOverride(tags={"compliance": "sox"}),
            "dev": EnvironmentOverride(
                instance_type_override="db.t4g.small",
                ec2_instance_type_override={"web": "t4g.small"},
                tags={"cost-center": "dev", "tier": "sandbox"},
            ),
        },
        environments=["prod", "dev"],
    )

    state = project_config_to_wizard_state(config)

    assert state["project_tags"] == {"owner": "platform"}
    assert state["_wizard_max_step_index"] == len(STEP_ORDER) - 1
    assert state["environment_overrides"]["prod"]["tags"] == {"compliance": "sox"}
    assert (
        state["environment_overrides"]["dev"]["instance_type_override"]
        == "db.t4g.small"
    )
    assert state["environment_overrides"]["dev"]["ec2_instance_type_override"] == {
        "web": "t4g.small"
    }

    rebuilt = build_config_from_state(state)

    assert rebuilt.tags == {"owner": "platform"}
    assert rebuilt.environment_overrides["prod"].tags == {"compliance": "sox"}
    assert rebuilt.environment_overrides["dev"].instance_type_override == "db.t4g.small"
    assert rebuilt.environment_overrides["dev"].ec2_instance_type_override == {
        "web": "t4g.small"
    }
    assert rebuilt.environment_overrides["dev"].tags == {
        "cost-center": "dev",
        "tier": "sandbox",
    }


def test_should_auto_fetch_saved_alb_skips_intermediate_transit_mounts() -> None:
    assert should_auto_fetch_saved_alb({"shared_alb_name": "shared-alb"}) is True
    assert (
        should_auto_fetch_saved_alb(
            {
                "shared_alb_name": "shared-alb",
                "_wizard_transit_target": "review",
            }
        )
        is False
    )
    assert (
        should_auto_fetch_saved_alb(
            {
                "shared_alb_name": "shared-alb",
                "_wizard_transit_target": "existing-resources",
            }
        )
        is True
    )
