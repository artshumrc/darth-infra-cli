from __future__ import annotations

from pathlib import Path

from darth_infra.cli.cfn import ResolvedLookupData, deploy_changeset
from darth_infra.config.models import (
    ActivePreviewEnvironment,
    ProjectConfig,
    ServiceConfig,
)


class _ListResourcesPaginator:
    def paginate(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "EcsCluster",
                        "ResourceType": "AWS::ECS::Cluster",
                        "PhysicalResourceId": "demo-ecs-pr-123",
                    }
                ]
            }
        ]


class _FakeCloudFormation:
    def __init__(self) -> None:
        self.execute_kwargs: dict[str, object] | None = None

    def describe_stacks(self, *, StackName: str) -> dict[str, object]:
        assert StackName == "demo-ecs-pr-123"
        return {"Stacks": [{"StackStatus": "CREATE_FAILED"}]}

    def get_paginator(self, name: str) -> _ListResourcesPaginator:
        assert name == "list_stack_resources"
        return _ListResourcesPaginator()

    def create_change_set(self, **_: object) -> dict[str, str]:
        return {"Id": "change-set-arn"}

    def describe_change_set(self, *, ChangeSetName: str) -> dict[str, object]:
        assert ChangeSetName == "change-set-arn"
        return {"Status": "CREATE_COMPLETE", "StatusReason": "", "Changes": []}

    def execute_change_set(self, **kwargs: object) -> None:
        self.execute_kwargs = kwargs


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


def test_preview_update_from_create_failed_executes_with_disable_rollback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    template_path = tmp_path / "packaged-root.yaml"
    template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", image="nginx:latest")],
    )
    config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.example.com",
        hosted_zone_name=None,
        tags={},
    )
    fake_cf = _FakeCloudFormation()

    def fake_client(service: str, **_: object) -> object:
        if service == "cloudformation":
            return fake_cf
        return object()

    monkeypatch.setattr("darth_infra.cli.cfn.boto3.client", fake_client)
    monkeypatch.setattr("darth_infra.cli.cfn._monitor_stack_deploy", lambda **_: True)

    rc = deploy_changeset(
        config,
        "pr-123",
        template_path,
        _lookups(),
        no_execute=False,
        changeset_name="retry-pr-123",
    )

    assert rc == 0
    assert fake_cf.execute_kwargs is not None
    assert fake_cf.execute_kwargs["DisableRollback"] is True
