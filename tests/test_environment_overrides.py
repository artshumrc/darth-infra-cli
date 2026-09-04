"""Per-environment overrides, and the container entrypoint override.

These cover the three ways one project config describes environments that differ
in more than their name: `[environments.<env>.services.<svc>]` for runtime
settings, `[environments.<env>.alb]` for shared-ALB targeting, and `{env}`
placeholders in an existing secret's name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darth_infra.cli.helpers import resolve_environment_config
from darth_infra.config.loader import dump_config, load_config
from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    EnvironmentAlbOverride,
    EnvironmentOverride,
    EnvironmentServiceOverride,
    ProjectConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates


def _config(**kwargs) -> ProjectConfig:
    defaults = dict(
        project_name="demo",
        environments=["prod", "dev"],
        services=[
            ServiceConfig(
                name="web",
                port=8000,
                cpu=1024,
                memory_mib=2048,
                environment_variables={"SITE_ID": "2", "SHARED": "same"},
            )
        ],
    )
    defaults.update(kwargs)
    return ProjectConfig(**defaults)


# -- service overrides -------------------------------------------------------


def test_service_override_replaces_scalars_and_merges_env_vars() -> None:
    config = _config(
        environment_overrides={
            "dev": EnvironmentOverride(
                services={
                    "web": EnvironmentServiceOverride(
                        cpu=512,
                        memory_mib=1024,
                        desired_count=0,
                        environment_variables={"SITE_ID": "1", "DJANGO_DEBUG": "True"},
                    )
                }
            )
        }
    )

    dev = resolve_environment_config(config, "dev")
    web = dev.services[0]

    assert (web.cpu, web.memory_mib, web.desired_count) == (512, 1024, 0)
    assert web.environment_variables == {
        "SITE_ID": "1",
        "SHARED": "same",
        "DJANGO_DEBUG": "True",
    }


def test_service_override_leaves_other_environments_alone() -> None:
    config = _config(
        environment_overrides={
            "dev": EnvironmentOverride(
                services={"web": EnvironmentServiceOverride(cpu=512)}
            )
        }
    )

    prod = resolve_environment_config(config, "prod")

    assert prod.services[0].cpu == 1024
    assert prod.services[0].environment_variables["SITE_ID"] == "2"


def test_service_override_omitted_fields_inherit() -> None:
    config = _config(
        environment_overrides={
            "dev": EnvironmentOverride(
                services={"web": EnvironmentServiceOverride(desired_count=3)}
            )
        }
    )

    web = resolve_environment_config(config, "dev").services[0]

    assert (web.cpu, web.memory_mib, web.desired_count) == (1024, 2048, 3)


def test_service_override_naming_an_unknown_service_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown service 'nope'"):
        _config(
            environment_overrides={
                "dev": EnvironmentOverride(
                    services={"nope": EnvironmentServiceOverride(cpu=512)}
                )
            }
        )


def test_service_override_reaches_the_rendered_task_definition() -> None:
    config = _config(
        environment_overrides={
            "dev": EnvironmentOverride(
                services={
                    "web": EnvironmentServiceOverride(
                        cpu=512,
                        memory_mib=1024,
                        environment_variables={"SITE_ID": "1"},
                    )
                }
            )
        }
    )

    dev = resolve_environment_config(config, "dev")
    template = build_project_templates(dev)["templates/generated/services/web.yaml"]
    task = template.to_dict()["Resources"]["TaskDefinition"]["Properties"]
    env = {item["Name"]: item["Value"] for item in task["ContainerDefinitions"][0]["Environment"]}

    assert task["Cpu"] == "512"
    assert task["Memory"] == "1024"
    assert env["SITE_ID"] == "1"


# -- ALB overrides -----------------------------------------------------------


def test_alb_override_retargets_the_shared_alb_per_environment() -> None:
    config = _config(
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="global-prod",
            domain="app.example.com",
            default_target_service="web",
        ),
        environment_overrides={
            "dev": EnvironmentOverride(
                alb=EnvironmentAlbOverride(shared_alb_name="global-dev")
            )
        },
    )

    assert resolve_environment_config(config, "prod").alb.shared_alb_name == "global-prod"
    assert resolve_environment_config(config, "dev").alb.shared_alb_name == "global-dev"


def test_alb_override_can_pin_listener_and_security_group() -> None:
    listener = (
        "arn:aws:elasticloadbalancing:us-east-1:407196791491:"
        "listener/app/global-dev/6f88af06/acb5c24f"
    )
    config = _config(
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="global-prod",
            domain="app.example.com",
            default_target_service="web",
        ),
        environment_overrides={
            "dev": EnvironmentOverride(
                alb=EnvironmentAlbOverride(
                    shared_listener_arn=listener,
                    shared_alb_security_group_id="sg-0123456789abcdef0",
                )
            )
        },
    )

    dev = resolve_environment_config(config, "dev")

    assert dev.alb.shared_listener_arn == listener
    assert dev.alb.shared_alb_security_group_id == "sg-0123456789abcdef0"
    # Unset fields still inherit, so name lookup remains the prod fallback.
    assert dev.alb.shared_alb_name == "global-prod"


def test_derived_dev_hostname_is_unaffected_by_an_alb_override() -> None:
    config = _config(
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="global-prod",
            domain="app.example.com",
            default_target_service="web",
        ),
        environment_overrides={
            "dev": EnvironmentOverride(
                alb=EnvironmentAlbOverride(shared_alb_name="global-dev")
            )
        },
    )

    assert (
        resolve_environment_config(config, "dev").get_cluster_domain("dev")
        == "dev.app.example.com"
    )


# -- existing_secret_name placeholders ---------------------------------------


def _secret_config(existing_secret_name: str) -> ProjectConfig:
    return _config(
        services=[
            ServiceConfig(name="web", port=8000, secrets=["DATABASE_URL"])
        ],
        secrets=[
            SecretConfig(
                name="DATABASE_URL",
                source=SecretSource.EXISTING,
                existing_secret_name=existing_secret_name,
            )
        ],
    )


@pytest.mark.parametrize("env_name", ["prod", "dev"])
def test_existing_secret_name_renders_project_and_env(env_name: str) -> None:
    config = _secret_config("{project}/{env}/DATABASE_URL")

    resolved = resolve_environment_config(config, env_name)

    assert resolved.secrets[0].existing_secret_name == f"demo/{env_name}/DATABASE_URL"


def test_existing_secret_name_without_placeholders_is_unchanged() -> None:
    config = _secret_config("legacy-shared-database-url")

    resolved = resolve_environment_config(config, "dev")

    assert resolved.secrets[0].existing_secret_name == "legacy-shared-database-url"


def test_existing_secret_arn_is_unchanged() -> None:
    arn = "arn:aws:secretsmanager:us-east-1:407196791491:secret:demo/dev/DATABASE_URL-AbCdEf"
    config = _secret_config(arn)

    assert resolve_environment_config(config, "dev").secrets[0].existing_secret_name == arn


def test_unresolvable_placeholder_is_left_for_the_deploy_time_lookup() -> None:
    config = _secret_config("{project}/{region}/DATABASE_URL")

    resolved = resolve_environment_config(config, "dev")

    assert resolved.secrets[0].existing_secret_name == "{project}/{region}/DATABASE_URL"


# -- entrypoint --------------------------------------------------------------


def test_entrypoint_is_emitted_in_exec_form() -> None:
    config = _config(
        services=[ServiceConfig(name="worker", port=None, entrypoint="/opt/app/huey.sh")]
    )

    template = build_project_templates(config)["templates/generated/services/worker.yaml"]
    container = template.to_dict()["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    assert container["EntryPoint"] == ["/opt/app/huey.sh"]


def test_entrypoint_splits_shell_words() -> None:
    config = _config(
        services=[
            ServiceConfig(name="worker", port=None, entrypoint="/bin/sh /opt/app/huey.sh")
        ]
    )

    template = build_project_templates(config)["templates/generated/services/worker.yaml"]
    container = template.to_dict()["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    assert container["EntryPoint"] == ["/bin/sh", "/opt/app/huey.sh"]


def test_no_entrypoint_key_when_unset() -> None:
    config = _config(services=[ServiceConfig(name="worker", port=None)])

    template = build_project_templates(config)["templates/generated/services/worker.yaml"]
    container = template.to_dict()["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    assert "EntryPoint" not in container


def test_entrypoint_and_command_coexist() -> None:
    config = _config(
        services=[
            ServiceConfig(
                name="worker",
                port=None,
                entrypoint="/opt/app/huey.sh",
                command="--workers 2",
            )
        ]
    )

    template = build_project_templates(config)["templates/generated/services/worker.yaml"]
    container = template.to_dict()["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    assert container["EntryPoint"] == ["/opt/app/huey.sh"]
    assert container["Command"] == ["sh", "-c", "--workers 2"]


# -- round-trip --------------------------------------------------------------


def test_every_new_field_survives_load_dump_load(tmp_path: Path) -> None:
    config_path = tmp_path / "darth-infra.toml"
    config_path.write_text(
        """#:schema ./darth-infra.schema.json

[project]
name = "demo"
environments = ["prod", "dev"]

[[services]]
name = "web"
port = 8000
cpu = 1024
memory_mib = 2048

[[services]]
name = "worker"
entrypoint = "/opt/app/huey.sh"

[alb]
mode = "shared"
shared_alb_name = "global-prod"
domain = "app.example.com"
default_target_service = "web"

[[secrets]]
name = "DATABASE_URL"
source = "existing"
existing_secret_name = "demo/{env}/DATABASE_URL"

[environments.dev.alb]
shared_alb_name = "global-dev"

[environments.dev.services.web]
cpu = 512
memory_mib = 1024
environment_variables = { SITE_ID = "1" }

[environments.dev.services.worker]
desired_count = 0
"""
    )

    first = load_config(config_path)
    config_path.write_text(dump_config(first))
    second = load_config(config_path)

    worker = next(s for s in second.services if s.name == "worker")
    assert worker.entrypoint == "/opt/app/huey.sh"
    assert second.secrets[0].existing_secret_name == "demo/{env}/DATABASE_URL"

    dev = second.environment_overrides["dev"]
    assert dev.alb.shared_alb_name == "global-dev"
    assert dev.services["web"].cpu == 512
    assert dev.services["web"].memory_mib == 1024
    assert dev.services["web"].environment_variables == {"SITE_ID": "1"}
    assert dev.services["worker"].desired_count == 0
    assert dev.services["worker"].cpu is None
