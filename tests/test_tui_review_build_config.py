from __future__ import annotations

from darth_infra.config.models import ProjectConfig, SecretConfig, ServiceConfig
from darth_infra.tui.screens.review import build_config_from_state
from darth_infra.tui.screens.services import merge_service_state
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

    assert {secret["name"]: secret.get("expose_to", []) for secret in state["secrets"]} == {
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
