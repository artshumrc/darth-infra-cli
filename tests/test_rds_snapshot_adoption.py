"""Adopting an unmanaged database by restoring prod's first deploy from a snapshot.

The invariant under test throughout: RDS treats ``DBSnapshotIdentifier`` as
sticky, so the deployed stack parameter always wins over configuration, and a
stack deployed without a snapshot must never acquire one.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from darth_infra.cli.cfn import (
    _resolve_rds_snapshot,
    _resolve_rds_source_secret_arn,
)
from darth_infra.config.loader import dump_config, load_config
from darth_infra.config.models import (
    ActivePreviewEnvironment,
    PreviewEnvironmentsConfig,
    ProjectConfig,
    RdsConfig,
    ServiceConfig,
)

_MISSING_STACK = ClientError(
    {"Error": {"Code": "ValidationError", "Message": "Stack with id x does not exist"}},
    "DescribeStacks",
)

_LEGACY_SNAPSHOT = "legacy-prod-final-2026-08-14"
_LEGACY_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:111122223333:secret:legacy-prod-credentials-AbCdEf"
)


def _config(
    snapshot: str | None = None, secret: str | None = None
) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        rds=RdsConfig(
            database_name="app",
            initial_snapshot_identifier=snapshot,
            initial_snapshot_credentials_secret=secret,
        ),
    )


class _FakeCloudFormation:
    """Stands in for a deployed stack, or its absence when parameters is None."""

    def __init__(self, parameters: dict[str, str] | None) -> None:
        self.parameters = parameters

    def describe_stacks(self, *, StackName: str) -> dict[str, object]:
        if self.parameters is None:
            raise _MISSING_STACK
        return {
            "Stacks": [
                {
                    "Parameters": [
                        {"ParameterKey": key, "ParameterValue": value}
                        for key, value in self.parameters.items()
                    ]
                }
            ]
        }


class _FakeRds:
    def __init__(self, known: set[str] | None = None) -> None:
        self.known = known if known is not None else {_LEGACY_SNAPSHOT}

    def describe_db_snapshots(self, **kwargs: object) -> dict[str, object]:
        identifier = kwargs.get("DBSnapshotIdentifier")
        if identifier in self.known:
            return {"DBSnapshots": [{"DBSnapshotIdentifier": identifier}]}
        return {"DBSnapshots": []}


class _FakeSecretsManager:
    def describe_secret(self, *, SecretId: str) -> dict[str, object]:
        if SecretId == "legacy-prod-credentials":
            return {"ARN": _LEGACY_SECRET_ARN}
        raise ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "DescribeSecret",
        )


def _patch_clients(
    monkeypatch,
    *,
    cloudformation: object | None = None,
    rds: object | None = None,
) -> None:
    clients = {
        "cloudformation": cloudformation if cloudformation is not None else _FakeCloudFormation(None),
        "rds": rds if rds is not None else _FakeRds(),
        "secretsmanager": _FakeSecretsManager(),
    }

    def fake_client(service: str, **_: object) -> object:
        if service not in clients:
            raise AssertionError(f"unexpected client: {service}")
        return clients[service]

    monkeypatch.setattr("darth_infra.cli.cfn.boto3.client", fake_client)


# -- prod first deploy -----------------------------------------------------


def test_prod_first_deploy_restores_from_configured_snapshot(monkeypatch) -> None:
    _patch_clients(monkeypatch)
    config = _config(_LEGACY_SNAPSHOT, "legacy-prod-credentials")

    assert _resolve_rds_snapshot(config, "prod") == _LEGACY_SNAPSHOT


def test_prod_first_deploy_without_configured_snapshot_starts_empty(monkeypatch) -> None:
    _patch_clients(monkeypatch)

    assert _resolve_rds_snapshot(_config(), "prod") == ""


def test_prod_first_deploy_rejects_a_snapshot_that_does_not_exist(monkeypatch) -> None:
    _patch_clients(monkeypatch, rds=_FakeRds(known=set()))
    config = _config("typo-snapshot", "legacy-prod-credentials")

    with pytest.raises(RuntimeError, match="typo-snapshot"):
        _resolve_rds_snapshot(config, "prod")


def test_prod_first_deploy_accepts_an_automated_snapshot_identifier(monkeypatch) -> None:
    automated = "rds:legacy-prod-db-2026-08-13-06-12"

    class _AutomatedOnlyRds:
        def describe_db_snapshots(self, **kwargs: object) -> dict[str, object]:
            # Mirrors RDS: an automated snapshot is invisible without SnapshotType.
            if kwargs.get("SnapshotType") != "automated":
                return {"DBSnapshots": []}
            return {"DBSnapshots": [{"DBSnapshotIdentifier": automated}]}

    _patch_clients(monkeypatch, rds=_AutomatedOnlyRds())
    config = _config(automated, "legacy-prod-credentials")

    assert _resolve_rds_snapshot(config, "prod") == automated


# -- stickiness ------------------------------------------------------------


def test_deployed_snapshot_identifier_wins_over_configuration(monkeypatch) -> None:
    _patch_clients(
        monkeypatch,
        cloudformation=_FakeCloudFormation({"RdsSnapshotIdentifier": _LEGACY_SNAPSHOT}),
        rds=_FakeRds(known={"a-newer-snapshot"}),
    )
    config = _config("a-newer-snapshot", "legacy-prod-credentials")

    assert _resolve_rds_snapshot(config, "prod") == _LEGACY_SNAPSHOT


def test_live_database_never_acquires_a_snapshot_identifier(monkeypatch) -> None:
    """Adding the key to an already-deployed project must not replace its data."""
    _patch_clients(
        monkeypatch,
        cloudformation=_FakeCloudFormation({"RdsSnapshotIdentifier": ""}),
    )
    config = _config(_LEGACY_SNAPSHOT, "legacy-prod-credentials")

    assert _resolve_rds_snapshot(config, "prod") == ""


def test_non_prod_reuses_its_deployed_snapshot_identifier(monkeypatch) -> None:
    class _NeverPolled:
        def describe_db_snapshots(self, **_: object) -> dict[str, object]:
            raise AssertionError("a deployed environment must not re-resolve a snapshot")

    _patch_clients(
        monkeypatch,
        cloudformation=_FakeCloudFormation(
            {"RdsSnapshotIdentifier": "rds:demo-prod-db-2026-05-22"}
        ),
        rds=_NeverPolled(),
    )

    assert _resolve_rds_snapshot(_config(), "dev") == "rds:demo-prod-db-2026-05-22"


def test_non_prod_first_deploy_seeds_from_latest_prod_snapshot(monkeypatch) -> None:
    class _ProdSnapshots:
        def describe_db_snapshots(self, **kwargs: object) -> dict[str, object]:
            assert kwargs["DBInstanceIdentifier"] == "demo-prod-db"
            assert kwargs["SnapshotType"] == "automated"
            return {
                "DBSnapshots": [
                    {"DBSnapshotIdentifier": "old", "SnapshotCreateTime": 1},
                    {"DBSnapshotIdentifier": "newest", "SnapshotCreateTime": 2},
                ]
            }

    _patch_clients(monkeypatch, rds=_ProdSnapshots())

    assert _resolve_rds_snapshot(_config(), "dev") == "newest"


# -- source credentials ----------------------------------------------------


def test_prod_source_secret_resolves_a_configured_name_to_an_arn(monkeypatch) -> None:
    _patch_clients(monkeypatch)
    config = _config(_LEGACY_SNAPSHOT, "legacy-prod-credentials")

    resolved = _resolve_rds_source_secret_arn(config, "prod", _LEGACY_SNAPSHOT)

    assert resolved == _LEGACY_SECRET_ARN


def test_prod_source_secret_passes_an_arn_through(monkeypatch) -> None:
    _patch_clients(monkeypatch)
    config = _config(_LEGACY_SNAPSHOT, _LEGACY_SECRET_ARN)

    resolved = _resolve_rds_source_secret_arn(config, "prod", _LEGACY_SNAPSHOT)

    assert resolved == _LEGACY_SECRET_ARN


def test_deployed_source_secret_wins_over_configuration(monkeypatch) -> None:
    deployed_arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:deployed-XyZ"
    _patch_clients(
        monkeypatch,
        cloudformation=_FakeCloudFormation({"RdsSourceSecretArn": deployed_arn}),
    )
    config = _config(_LEGACY_SNAPSHOT, "legacy-prod-credentials")

    resolved = _resolve_rds_source_secret_arn(config, "prod", _LEGACY_SNAPSHOT)

    assert resolved == deployed_arn


def test_dropping_the_credentials_key_after_adoption_is_an_error(monkeypatch) -> None:
    """The secret re-resolves every deploy, so the key cannot be removed later."""
    _patch_clients(
        monkeypatch,
        cloudformation=_FakeCloudFormation(
            {"RdsSnapshotIdentifier": _LEGACY_SNAPSHOT, "RdsSourceSecretArn": ""}
        ),
    )

    with pytest.raises(RuntimeError, match="initial_snapshot_credentials_secret"):
        _resolve_rds_source_secret_arn(_config(), "prod", _LEGACY_SNAPSHOT)


def test_no_snapshot_means_no_source_secret(monkeypatch) -> None:
    _patch_clients(monkeypatch)

    assert _resolve_rds_source_secret_arn(_config(), "prod", "") == ""


def test_plain_non_prod_environment_resolves_prod_credentials(monkeypatch) -> None:
    """A snapshot-seeded environment always needs source credentials, preview or not."""

    class _ProdStack(_FakeCloudFormation):
        def describe_stack_resource(
            self, *, StackName: str, LogicalResourceId: str
        ) -> dict[str, object]:
            assert StackName == "demo-ecs-prod"
            assert LogicalResourceId == "RdsCredentialsSecret"
            return {"StackResourceDetail": {"PhysicalResourceId": _LEGACY_SECRET_ARN}}

    _patch_clients(monkeypatch, cloudformation=_ProdStack(None))

    resolved = _resolve_rds_source_secret_arn(_config(), "dev", "some-snapshot")

    assert resolved == _LEGACY_SECRET_ARN


def test_preview_still_resolves_prod_credentials(monkeypatch) -> None:
    class _ProdStack(_FakeCloudFormation):
        def describe_stack_resource(self, **_: object) -> dict[str, object]:
            return {"StackResourceDetail": {"PhysicalResourceId": _LEGACY_SECRET_ARN}}

    config = _config()
    config.preview_environments = PreviewEnvironmentsConfig(
        enabled=True,
        base_environment="prod",
        name_pattern="pr-{number}",
        domain_template="pr-{number}.example.com",
    )
    config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.example.com",
        hosted_zone_name=None,
        tags={},
    )
    _patch_clients(monkeypatch, cloudformation=_ProdStack(None))

    resolved = _resolve_rds_source_secret_arn(config, "pr-123", "some-snapshot")

    assert resolved == _LEGACY_SECRET_ARN


# -- configuration surface -------------------------------------------------


def test_snapshot_identifier_requires_credentials_secret() -> None:
    with pytest.raises(ValueError, match="initial_snapshot_credentials_secret"):
        _config(_LEGACY_SNAPSHOT, None)


def test_credentials_secret_requires_snapshot_identifier() -> None:
    with pytest.raises(ValueError, match="initial_snapshot_identifier"):
        _config(None, "legacy-prod-credentials")


def test_adoption_keys_survive_a_config_rewrite(tmp_path) -> None:
    """The TUI rewrites the whole file; dropping these keys would replace the DB."""
    config = _config(_LEGACY_SNAPSHOT, "legacy-prod-credentials")
    path = tmp_path / "darth-infra.toml"
    path.write_text(dump_config(config), encoding="utf-8")

    reloaded = load_config(path)

    assert reloaded.rds is not None
    assert reloaded.rds.initial_snapshot_identifier == _LEGACY_SNAPSHOT
    assert reloaded.rds.initial_snapshot_credentials_secret == "legacy-prod-credentials"
