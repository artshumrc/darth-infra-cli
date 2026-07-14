"""Unit tests for the structural (object-tree) deploy-time validator.

These exercise ``validate_built_deploy_templates``, which consumes the
troposphere ``Template`` objects from ``build_project_templates`` directly
(via ``Template.to_dict()``) instead of substring-matching rendered YAML.
The validator lands inert here: it is not yet wired into the deploy path
(ticket 10 performs that cutover).
"""

from __future__ import annotations

import pytest

from darth_infra.cli.cfn import (
    ResolvedLookupData,
    validate_built_deploy_templates,
)
from darth_infra.config.models import (
    ProjectConfig,
    RdsConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates


def _lookups() -> ResolvedLookupData:
    return ResolvedLookupData(
        vpc_id="vpc-123",
        vpc_cidr="10.0.0.0/16",
        private_subnet_ids=["subnet-a"],
        public_subnet_ids=["subnet-b"],
        shared_listener_arn="listener-arn",
        shared_alb_security_group_id="sg-123",
        shared_alb_dns_name="alb.example.com",
        shared_alb_canonical_hosted_zone_id="ZALB123",
        hosted_zone_id="",
        default_listener_priority=100,
        path_rule_priorities={},
        rds_snapshot_identifier="",
        rds_source_secret_arn="",
        external_secret_arns={
            "DJANGO_SECRET_KEY": "arn:aws:secretsmanager:us-east-1:123456789012:secret:django",
        },
        existing_service_discovery_namespace_id="",
    )


def _config(*, enable_ses_send_email: bool = False) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="web",
                port=8000,
                enable_ses_send_email=enable_ses_send_email,
                secrets=[
                    "DJANGO_SECRET_KEY",
                    "POSTGRES_HOST",
                    "POSTGRES_PORT",
                ],
            )
        ],
        secrets=[
            SecretConfig(
                name="DJANGO_SECRET_KEY",
                source=SecretSource.EXISTING,
                existing_secret_name="arn:aws:secretsmanager:us-east-1:123456789012:secret:django",
            ),
            SecretConfig(
                name="POSTGRES_HOST",
                source=SecretSource.RDS,
                existing_secret_name="host",
            ),
            SecretConfig(
                name="POSTGRES_PORT",
                source=SecretSource.RDS,
                existing_secret_name="port",
            ),
        ],
        rds=RdsConfig(database_name="demo", expose_to=["web"]),
    )


def _generate_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000, secrets=["APP_SECRET"])],
        secrets=[SecretConfig(name="APP_SECRET", source=SecretSource.GENERATE)],
    )


# --- passing on correct fixtures -------------------------------------------


def test_accepts_expected_secret_wiring() -> None:
    templates = build_project_templates(_config())
    validate_built_deploy_templates(templates, _config(), "prod", _lookups())


def test_accepts_expected_ses_wiring() -> None:
    config = _config(enable_ses_send_email=True)
    templates = build_project_templates(config)
    validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_accepts_generated_secret_wiring() -> None:
    config = _generate_config()
    templates = build_project_templates(config)
    validate_built_deploy_templates(templates, config, "prod", _lookups())


# --- raising on missing SES policy -----------------------------------------


def test_rejects_missing_ses_policy() -> None:
    config = _config(enable_ses_send_email=True)
    templates = build_project_templates(config)
    task_role = templates["templates/generated/services/web.yaml"].resources[
        "TaskRole"
    ]
    task_role.properties["Policies"] = [
        policy
        for policy in task_role.properties["Policies"]
        if policy.properties.get("PolicyName") != "SesSendEmail"
    ]

    with pytest.raises(RuntimeError, match="SES task-role policy"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_rejects_incomplete_ses_action_list() -> None:
    config = _config(enable_ses_send_email=True)
    templates = build_project_templates(config)
    task_role = templates["templates/generated/services/web.yaml"].resources[
        "TaskRole"
    ]
    for policy in task_role.properties["Policies"]:
        if policy.properties.get("PolicyName") == "SesSendEmail":
            statement = policy.properties["PolicyDocument"]["Statement"][0]
            statement["Action"] = [
                action
                for action in statement["Action"]
                if action != "ses:GetSendQuota"
            ]

    with pytest.raises(RuntimeError, match="SES task-role policy"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


# --- raising on missing RDS secret wiring ----------------------------------


def test_rejects_missing_rds_secret_from_task_definition() -> None:
    config = _config()
    templates = build_project_templates(config)
    container = (
        templates["templates/generated/services/web.yaml"]
        .resources["TaskDefinition"]
        .properties["ContainerDefinitions"][0]
    )
    container.properties["Secrets"] = [
        secret
        for secret in container.properties["Secrets"]
        if secret.properties.get("Name") != "POSTGRES_HOST"
    ]

    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_rejects_missing_rds_secret_source_from_execution_role() -> None:
    config = _config()
    templates = build_project_templates(config)
    exec_role = templates["templates/generated/services/web.yaml"].resources[
        "TaskExecutionRole"
    ]
    for policy in exec_role.properties["Policies"]:
        if policy.properties.get("PolicyName") == "ReadSecrets":
            statement = policy.properties["PolicyDocument"]["Statement"][0]
            statement["Resource"] = [
                ref for ref in statement["Resource"] if ref.data != {"Ref": "RdsSecretArn"}
            ]

    with pytest.raises(RuntimeError, match="RdsSecretArn"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_rejects_missing_root_rds_secret_arn_wiring() -> None:
    config = _config()
    templates = build_project_templates(config)
    for resource in templates["templates/generated/root.yaml"].resources.values():
        if getattr(resource, "resource_type", None) == "AWS::CloudFormation::Stack":
            params = resource.properties.get("Parameters", {})
            params.pop("RdsSecretArn", None)

    with pytest.raises(RuntimeError, match="nested RDS secret ARN wiring"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


# --- raising on missing non-RDS secret wiring ------------------------------


def test_rejects_missing_execution_role_secret_access() -> None:
    config = _config()
    templates = build_project_templates(config)
    exec_role = templates["templates/generated/services/web.yaml"].resources[
        "TaskExecutionRole"
    ]
    for policy in exec_role.properties["Policies"]:
        if policy.properties.get("PolicyName") == "ReadSecrets":
            statement = policy.properties["PolicyDocument"]["Statement"][0]
            statement["Resource"] = [
                ref
                for ref in statement["Resource"]
                if ref.data != {"Ref": "SecretArnDJANGOSECRETKEY"}
            ]

    with pytest.raises(RuntimeError, match="DJANGO_SECRET_KEY"):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_rejects_missing_external_secret_arn_resolution() -> None:
    config = _config()
    templates = build_project_templates(config)
    lookups = _lookups()
    lookups.external_secret_arns.pop("DJANGO_SECRET_KEY")

    with pytest.raises(RuntimeError, match="did not resolve to an ARN"):
        validate_built_deploy_templates(templates, config, "prod", lookups)


# --- missing template files ------------------------------------------------


def test_rejects_missing_root_template() -> None:
    config = _config()
    templates = build_project_templates(config)
    del templates["templates/generated/root.yaml"]

    with pytest.raises(FileNotFoundError):
        validate_built_deploy_templates(templates, config, "prod", _lookups())


def test_rejects_missing_service_template() -> None:
    config = _config()
    templates = build_project_templates(config)
    del templates["templates/generated/services/web.yaml"]

    with pytest.raises(FileNotFoundError):
        validate_built_deploy_templates(templates, config, "prod", _lookups())
