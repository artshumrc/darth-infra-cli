from dataclasses import FrozenInstanceError

import pytest

from darth_infra.config.models import (
    AlbConfig,
    AlbPathRule,
    EnvironmentOverride,
    ProjectConfig,
    RdsConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.context import RenderContext, derive_render_context


def test_context_derives_stable_cloudformation_names() -> None:
    config = ProjectConfig(
        project_name="demo-app",
        services=[
            ServiceConfig(
                name="web-api",
                port=8000,
                secrets=["db_secret-key"],
            )
        ],
        rds=RdsConfig(
            database_name="Customer_Data_Archive2026",
            expose_to=["web-api"],
        ),
        alb=AlbConfig(
            domain="app.example.com",
            default_target_service="web-api",
            path_rules=[
                AlbPathRule(
                    name="api-v2",
                    path_pattern="/api/v2/*",
                    target_service="web-api",
                )
            ],
        ),
        secrets=[
            SecretConfig(
                name="db_secret-key",
                source=SecretSource.RDS,
                existing_secret_name="RDS Database Name",
            )
        ],
        tags={"owner": "platform"},
        environment_overrides={
            "dev": EnvironmentOverride(tags={"cost-center": "sandbox"})
        },
    )

    context = derive_render_context(config)

    assert isinstance(context, RenderContext)
    assert context.project_name_pascal == "DemoApp"
    assert context.rds_master_username == "customerdataarch"
    assert [
        (tag.key, tag.parameter_name, tag.condition_name)
        for tag in context.tag_parameters
        if tag.key in {"cost-center", "owner"}
    ] == [
        ("cost-center", "ExtraTagCostCenter", "HasExtraTagCostCenter"),
        ("owner", "ExtraTagOwner", "HasExtraTagOwner"),
    ]

    secret = context.secrets[0]
    assert secret.logical_id_fragment == "dbsecretkey"
    assert secret.generated_secret_logical_id == "Secretdbsecretkey"
    assert secret.external_parameter_name == "EnvSecretArndbsecretkey"

    service = context.services_ctx[0]
    assert service.name_pascal == "WebApi"
    assert service.default_listener_priority_param_name == "DefaultListenerPriority"
    assert service.secret_params[0].param_name == "SecretArnDbSecretKey"
    assert service.secret_params[0].rds_json_key == "dbname"
    assert [rule.priority_param_name for rule in service.service_path_rules] == [
        "PathRulePriorityApiV2"
    ]

    with pytest.raises(FrozenInstanceError):
        context.project_name = "changed"
