from pathlib import Path

from darth_infra.config.loader import dump_config, load_config
from darth_infra.config.models import (
    ActivePreviewEnvironment,
    PreviewEnvironmentsConfig,
    ProjectConfig,
    RdsConfig,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates

from builders_harness import assert_template_passes_cfn_lint, template_to_dict

_BACKUP_IDS = (
    "RdsBackupBucket",
    "RdsBackupLogGroup",
    "RdsBackupSecurityGroup",
    "RdsIngressFromBackup",
    "RdsBackupExecutionRole",
    "RdsBackupTaskRole",
    "RdsBackupTaskDefinition",
    "RdsBackupSchedulerRole",
    "RdsBackupScheduleGroup",
    "RdsBackupSchedule",
)
_ALERT_IDS = (
    "RdsBackupAlertTopic",
    "RdsBackupFailureRule",
    "RdsBackupInvocationAlarm",
    "RdsBackupAlertTopicPolicy",
)


def _config(**rds: object) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        rds=RdsConfig(database_name="app", expose_to=["web"], **rds),
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            listener_priority_start=30000,
            listener_priority_end=30005,
        ),
    )


def _root(config: ProjectConfig) -> dict:
    return template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )


def test_rds_defaults_keep_35_days_and_back_up_monthly() -> None:
    root = _root(_config(engine_version="16.4"))
    resources = root["Resources"]

    assert resources["Database"]["Properties"]["BackupRetentionPeriod"] == 35
    for logical_id in _BACKUP_IDS + _ALERT_IDS:
        assert resources[logical_id]["Condition"] == "IsProd"

    bucket = resources["RdsBackupBucket"]
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    assert {"Key": "Purpose", "Value": "rds-backup"} in bucket["Properties"]["Tags"]
    assert {"Key": "Project", "Value": {"Ref": "ProjectName"}} in bucket[
        "Properties"
    ]["Tags"]

    container = resources["RdsBackupTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]
    assert container["Image"] == "public.ecr.aws/docker/library/postgres:16-alpine"
    assert "--storage-class GLACIER_IR" in container["Command"][0]
    assert "multipart_chunksize 64MB" in container["Command"][0]
    assert resources["RdsBackupSchedule"]["Properties"]["GroupName"] == {
        "Ref": "RdsBackupScheduleGroup"
    }
    assert resources["RdsBackupInvocationAlarm"]["Properties"]["Dimensions"] == [
        {"Name": "ScheduleGroup", "Value": {"Ref": "RdsBackupScheduleGroup"}}
    ]
    assert (
        resources["RdsBackupSchedule"]["Properties"]["ScheduleExpression"]
        == "cron(0 5 1 * ? *)"
    )
    assert resources["RdsBackupAlertTopic"]["Properties"]["Subscription"] == [
        {"Endpoint": "artshum-rc@fas.harvard.edu", "Protocol": "email"}
    ]


def test_monthly_backup_can_be_disabled() -> None:
    resources = _root(_config(monthly_s3_backup=False))["Resources"]

    assert not set(_BACKUP_IDS + _ALERT_IDS) & set(resources)


def test_empty_alert_email_omits_alerting() -> None:
    resources = _root(_config(backup_alert_email="  "))["Resources"]

    assert "RdsBackupSchedule" in resources
    assert not set(_ALERT_IDS) & set(resources)


def test_preview_environments_render_no_backup() -> None:
    config = _config()
    config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.example.com",
        hosted_zone_name=None,
        tags={},
    )

    assert not set(_BACKUP_IDS + _ALERT_IDS) & set(_root(config)["Resources"])


def test_backup_root_passes_cfn_lint(tmp_path: Path) -> None:
    root = build_project_templates(_config())["templates/generated/root.yaml"]

    assert_template_passes_cfn_lint(root, tmp_path / "root.yaml")


def test_loader_defaults_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "darth-infra.toml"
    path.write_text(
        '[project]\nname = "demo"\n\n'
        '[[services]]\nname = "web"\nport = 8000\n\n'
        '[rds]\ndatabase_name = "app"\n'
    )
    rds = load_config(path).rds
    assert rds is not None
    assert rds.backup_retention_days == 35
    assert rds.monthly_s3_backup is True
    assert rds.backup_alert_email == "artshum-rc@fas.harvard.edu"

    config = load_config(path)
    config.rds.monthly_s3_backup = False
    config.rds.backup_alert_email = ""
    path.write_text(dump_config(config))
    reloaded = load_config(path).rds
    assert reloaded.monthly_s3_backup is False
    assert reloaded.backup_alert_email == ""
