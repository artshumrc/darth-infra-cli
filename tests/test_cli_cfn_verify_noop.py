"""Unit tests for the ``--verify-noop`` release gate (mocked boto3).

These exercise ``deploy_changeset(..., verify_noop=True)`` — the same code path
``darth-infra deploy --verify-noop`` runs — against hand-rolled fake
CloudFormation clients. The real-stack acceptance criteria in ticket 11 require
AWS credentials and are left to the release manager; these tests prove the
decision logic and change-set cleanup.
"""

from __future__ import annotations

from pathlib import Path

from darth_infra.cli.cfn import ResolvedLookupData, deploy_changeset
from darth_infra.config.models import ProjectConfig, ServiceConfig


class _ListResourcesPaginator:
    def paginate(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "EcsCluster",
                        "ResourceType": "AWS::ECS::Cluster",
                        "PhysicalResourceId": "demo-ecs-prod",
                    }
                ]
            }
        ]


class _FakeCloudFormation:
    """Minimal fake CloudFormation client for the verify-noop path."""

    def __init__(self, changeset_result: dict[str, object]) -> None:
        self._changeset_result = changeset_result
        self.created = False
        self.executed = False
        self.deleted_change_sets: list[str] = []

    def describe_stacks(self, *, StackName: str) -> dict[str, object]:
        # Existing, healthy stack -> UPDATE change set (verify runs on real stacks).
        return {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]}

    def get_paginator(self, name: str) -> _ListResourcesPaginator:
        assert name == "list_stack_resources"
        return _ListResourcesPaginator()

    def create_change_set(self, **_: object) -> dict[str, str]:
        self.created = True
        return {"Id": "change-set-arn"}

    def describe_change_set(self, **_: object) -> dict[str, object]:
        return self._changeset_result

    def delete_change_set(self, *, ChangeSetName: str) -> None:
        self.deleted_change_sets.append(ChangeSetName)

    def execute_change_set(self, **_: object) -> None:  # pragma: no cover
        self.executed = True

    def describe_stack_events(self, **_: object) -> dict[str, object]:
        return {"StackEvents": []}


def _lookups() -> ResolvedLookupData:
    return ResolvedLookupData(
        vpc_id="vpc-12345678",
        vpc_cidr="10.0.0.0/16",
        private_subnet_ids=["subnet-11111111"],
        public_subnet_ids=["subnet-22222222"],
        shared_listener_arn="listener-arn",
        shared_alb_security_group_id="sg-12345678",
        shared_alb_dns_name="alb.example.com",
        shared_alb_canonical_hosted_zone_id="ZALB123",
        hosted_zone_id="ZHOSTED123",
        default_listener_priority=None,
        path_rule_priorities={},
        rds_snapshot_identifier="",
        rds_source_secret_arn="",
        external_secret_arns={},
        existing_service_discovery_namespace_id="",
    )


def _config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", image="nginx:latest")],
    )


def _run(
    tmp_path: Path,
    monkeypatch,
    changeset_result: dict[str, object],
) -> tuple[int, _FakeCloudFormation]:
    template_path = tmp_path / "packaged-root.yaml"
    template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\n")

    fake_cf = _FakeCloudFormation(changeset_result)

    def fake_client(service: str, **_: object) -> object:
        if service == "cloudformation":
            return fake_cf
        return object()

    monkeypatch.setattr("darth_infra.cli.cfn.boto3.client", fake_client)

    rc = deploy_changeset(
        _config(),
        "prod",
        template_path,
        _lookups(),
        no_execute=True,
        changeset_name="verify-prod",
        verify_noop=True,
    )
    return rc, fake_cf


def test_empty_change_set_passes_and_is_deleted(tmp_path: Path, monkeypatch) -> None:
    # CloudFormation fails creation of an empty change set: the success signal.
    rc, fake_cf = _run(
        tmp_path,
        monkeypatch,
        {
            "Status": "FAILED",
            "StatusReason": "The submitted information didn't contain changes. "
            "Submit different information to create a change set.",
            "Changes": [],
        },
    )

    assert rc == 0
    assert fake_cf.created is True
    assert fake_cf.executed is False
    assert fake_cf.deleted_change_sets == ["change-set-arn"]


def test_change_set_with_resource_changes_fails_and_is_deleted(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    rc, fake_cf = _run(
        tmp_path,
        monkeypatch,
        {
            "Status": "CREATE_COMPLETE",
            "StatusReason": "",
            "Changes": [
                {
                    "ResourceChange": {
                        "Action": "Modify",
                        "LogicalResourceId": "WebTaskDefinition",
                        "ResourceType": "AWS::ECS::TaskDefinition",
                    }
                },
                {
                    "ResourceChange": {
                        "Action": "Modify",
                        "LogicalResourceId": "WebService",
                        "ResourceType": "AWS::ECS::Service",
                    }
                },
            ],
        },
    )

    assert rc == 1
    assert fake_cf.executed is False
    assert fake_cf.deleted_change_sets == ["change-set-arn"]

    output = capsys.readouterr().out
    assert "WebTaskDefinition" in output
    assert "WebService" in output


def test_change_set_complete_without_changes_passes_and_is_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    rc, fake_cf = _run(
        tmp_path,
        monkeypatch,
        {"Status": "CREATE_COMPLETE", "StatusReason": "", "Changes": []},
    )

    assert rc == 0
    assert fake_cf.executed is False
    assert fake_cf.deleted_change_sets == ["change-set-arn"]
