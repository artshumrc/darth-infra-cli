from __future__ import annotations

from pathlib import Path
import tempfile

from darth_infra.cli.cfn import (
    ResolvedLookupData,
    _ecs_rollout_is_stable,
    _is_fatal_ecs_startup_message,
    validate_rendered_deploy_templates,
)
from darth_infra.config.models import (
    ProjectConfig,
    RdsConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.generator import generate_project


def _lookups() -> ResolvedLookupData:
    return ResolvedLookupData(
        vpc_id="vpc-123",
        vpc_cidr="10.0.0.0/16",
        private_subnet_ids=["subnet-a"],
        public_subnet_ids=["subnet-b"],
        shared_listener_arn="listener-arn",
        shared_alb_security_group_id="sg-123",
        shared_alb_dns_name="alb.example.com",
        default_listener_priority=100,
        path_rule_priorities={},
        rds_snapshot_identifier="",
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


def _read(path: Path) -> str:
    return path.read_text()


def test_root_template_passes_secret_arns_to_nested_service(tmp_path: Path) -> None:
    output_dir = generate_project(_config(), tmp_path / "out")
    root = _read(output_dir / "templates" / "generated" / "root.yaml")

    assert "SecretArnDJANGOSECRETKEY: !Ref EnvSecretArnDJANGOSECRETKEY" in root
    assert "RdsSecretArn: !GetAtt RdsCredentialsSecret.Arn" in root


def test_validate_rendered_templates_accepts_expected_secret_wiring(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(_config(), tmp_path / "out")
    validate_rendered_deploy_templates(output_dir, _config(), "prod", _lookups())


def test_service_template_includes_ses_task_role_policy_when_enabled(
    tmp_path: Path,
) -> None:
    config = _config(enable_ses_send_email=True)
    output_dir = generate_project(config, tmp_path / "out")
    service_body = _read(output_dir / "templates" / "generated" / "services" / "web.yaml")

    assert "PolicyName: SesSendEmail" in service_body
    assert "- ses:SendEmail" in service_body
    assert "- ses:SendRawEmail" in service_body
    assert "- ses:GetSendQuota" in service_body


def test_service_template_renders_valid_exec_task_role_policy_block(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(_config(), tmp_path / "out")
    service_body = _read(output_dir / "templates" / "generated" / "services" / "web.yaml")

    assert (
        """        - PolicyName: EcsExecSsm
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - ssmmessages:CreateControlChannel
                  - ssmmessages:CreateDataChannel
                  - ssmmessages:OpenControlChannel
                  - ssmmessages:OpenDataChannel
                Resource: '*'"""
        in service_body
    )


def test_validate_rendered_templates_accepts_expected_ses_wiring(
    tmp_path: Path,
) -> None:
    config = _config(enable_ses_send_email=True)
    output_dir = generate_project(config, tmp_path / "out")

    validate_rendered_deploy_templates(output_dir, config, "prod", _lookups())


def test_validate_rendered_templates_rejects_missing_execution_role_secret_access(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(_config(), tmp_path / "out")
    service_template = output_dir / "templates" / "generated" / "services" / "web.yaml"
    original = service_template.read_text()
    service_template.write_text(original.replace("- !Ref SecretArnDJANGOSECRETKEY\n", ""))

    try:
        validate_rendered_deploy_templates(output_dir, _config(), "prod", _lookups())
    except RuntimeError as exc:
        assert "DJANGO_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("expected validate_rendered_deploy_templates() to fail")


def test_validate_rendered_templates_rejects_missing_ses_task_role_access(
    tmp_path: Path,
) -> None:
    config = _config(enable_ses_send_email=True)
    output_dir = generate_project(config, tmp_path / "out")
    service_template = output_dir / "templates" / "generated" / "services" / "web.yaml"
    original = service_template.read_text()
    service_template.write_text(original.replace("- ses:GetSendQuota\n", ""))

    try:
        validate_rendered_deploy_templates(output_dir, config, "prod", _lookups())
    except RuntimeError as exc:
        assert "SES task-role policy" in str(exc)
    else:
        raise AssertionError("expected validate_rendered_deploy_templates() to fail")


def test_rollout_stability_requires_active_single_deployment() -> None:
    assert _ecs_rollout_is_stable(
        {
            "rows": [
                {
                    "service": "web",
                    "status": "ACTIVE",
                    "running": "1",
                    "desired": "1",
                    "pending": "0",
                    "deployments": "1",
                }
            ]
        }
    )
    assert not _ecs_rollout_is_stable(
        {
            "rows": [
                {
                    "service": "web",
                    "status": "ACTIVE",
                    "running": "0",
                    "desired": "1",
                    "pending": "1",
                    "deployments": "2",
                }
            ]
        }
    )


def test_fatal_ecs_startup_message_detection_matches_secret_access_failures() -> None:
    assert _is_fatal_ecs_startup_message(
        "ResourceInitializationError: unable to pull secrets or registry auth"
    )
    assert _is_fatal_ecs_startup_message(
        "AccessDeniedException: no identity-based policy allows the secretsmanager:GetSecretValue action"
    )
    assert not _is_fatal_ecs_startup_message("service reached steady state")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_root_template_passes_secret_arns_to_nested_service(tmp_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_validate_rendered_templates_accepts_expected_secret_wiring(tmp_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_service_template_includes_ses_task_role_policy_when_enabled(tmp_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_validate_rendered_templates_accepts_expected_ses_wiring(tmp_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_validate_rendered_templates_rejects_missing_execution_role_secret_access(
            tmp_path
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_validate_rendered_templates_rejects_missing_ses_task_role_access(
            tmp_path
        )
    test_rollout_stability_requires_active_single_deployment()
    test_fatal_ecs_startup_message_detection_matches_secret_access_failures()
