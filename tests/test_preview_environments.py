from __future__ import annotations

from pathlib import Path

import pytest

from darth_infra.cli.cfn import (
    ResolvedLookupData,
    _build_parameters,
    _resolve_listener_priorities,
    _resolve_rds_snapshot,
)
from darth_infra.cli.helpers import resolve_environment_config
from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import dump_config, load_config
from darth_infra.config.models import (
    ActivePreviewEnvironment,
    AlbConfig,
    AlbMode,
    AlbPathRule,
    EnvironmentOverride,
    PreviewEnvironmentsConfig,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    S3BucketConnection,
    S3BucketMode,
    ServiceDiscoveryConfig,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates


def _config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="web",
                environment_variables={"BASE_DOMAIN": "{domain}"},
            )
        ],
        tags={"owner": "platform"},
        environment_overrides={"prod": EnvironmentOverride(tags={"huit_assetid": "12057"})},
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.bta.darthcrimson.org",
            hosted_zone_name="darthcrimson.org",
            listener_priority_start=30000,
            listener_priority_end=39999,
            tags={"ephemeral-cleanup-id": "{project}-{env}"},
        ),
    )


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
        default_listener_priority=30000,
        path_rule_priorities={},
        rds_snapshot_identifier="",
        rds_source_secret_arn="",
        external_secret_arns={},
        existing_service_discovery_namespace_id="",
    )


class _RulePaginator:
    def __init__(self, rules: list[dict[str, object]]) -> None:
        self.rules = rules

    def paginate(self, **_: object) -> list[dict[str, object]]:
        return [{"Rules": self.rules}]


class _FakeElbv2Rules:
    def __init__(self, rules: list[dict[str, object]] | None = None) -> None:
        self.rules = rules or []

    def get_paginator(self, name: str) -> _RulePaginator:
        assert name == "describe_rules"
        return _RulePaginator(self.rules)


def test_listener_arn_derived_from_rule_arn() -> None:
    from darth_infra.cli.cfn import _listener_arn_from_rule_arn

    rule = (
        "arn:aws:elasticloadbalancing:us-east-1:407196791491:"
        "listener-rule/app/global-prod/6f88af06/acb5c24f/b7d3f009"
    )
    assert _listener_arn_from_rule_arn(rule) == (
        "arn:aws:elasticloadbalancing:us-east-1:407196791491:"
        "listener/app/global-prod/6f88af06/acb5c24f"
    )
    assert _listener_arn_from_rule_arn("not-a-rule-arn") == ""


def test_stack_owned_priority_detected_when_describe_rules_omits_listener_arn(
    monkeypatch,
) -> None:
    """Regression: describe_rules(RuleArns=...) does not return a ListenerArn
    field, so filtering rules on rule["ListenerArn"] dropped every stack-owned
    rule, causing the deploy to reassign existing priorities (e.g. 49991 -> 1)
    on every deploy. The listener must be derived from the rule's own ARN."""
    from darth_infra.cli import cfn

    listener = (
        "arn:aws:elasticloadbalancing:us-east-1:1:listener/app/lb/lbid/lsid"
    )
    rule_arn = (
        "arn:aws:elasticloadbalancing:us-east-1:1:"
        "listener-rule/app/lb/lbid/lsid/ruleid"
    )

    monkeypatch.setattr(
        cfn,
        "_list_listener_rule_resources_for_stack",
        lambda cf, stack, visited=None: [("DefaultHostHeaderRule", rule_arn)],
    )
    monkeypatch.setattr(cfn.boto3, "client", lambda *a, **k: object())

    class _FakeElb:
        def describe_rules(self, *, RuleArns):
            # Mirror real AWS: no ListenerArn key on each rule.
            return {"Rules": [{"RuleArn": RuleArns[0], "Priority": "49991"}]}

    config = ProjectConfig(project_name="demo", services=[ServiceConfig(name="web")])
    result = cfn._resolve_stack_owned_listener_rule_priorities_by_label(
        config, "prod", listener, _FakeElb()
    )

    assert result == {"default": 49991}


def test_preview_config_load_and_dump_roundtrip(tmp_path: Path) -> None:
    config_path = tmp_path / "darth-infra.toml"
    config_path.write_text(dump_config(_config()))

    loaded = load_config(config_path)

    assert loaded.preview_environments.enabled is True
    assert loaded.preview_environments.domain_template == "pr-{number}.bta.darthcrimson.org"
    assert loaded.preview_environments.hosted_zone_name == "darthcrimson.org"
    assert loaded.preview_environments.tags == {"ephemeral-cleanup-id": "{project}-{env}"}


def test_dynamic_preview_excludes_prod_tags_and_adds_cleanup_tag() -> None:
    preview_config = resolve_environment_config(_config(), "pr-123", "prod")

    tags = preview_config.get_tags_for_environment("pr-123")

    assert tags["owner"] == "platform"
    assert tags["environment-type"] == "preview"
    assert tags["preview-base-environment"] == "prod"
    assert tags["pull-request"] == "123"
    assert tags["ephemeral-cleanup-id"] == "demo-pr-123"
    assert "huit_assetid" not in tags
    assert preview_config.get_cluster_domain("pr-123") == "pr-123.bta.darthcrimson.org"
    assert preview_config.services[0].environment_variables["BASE_DOMAIN"] == "https://pr-123.bta.darthcrimson.org"


def test_dynamic_preview_inherits_base_non_tag_overrides_only() -> None:
    config = _config()
    config.environment_overrides["prod"] = EnvironmentOverride(
        instance_type_override="db.t4g.small",
        ec2_instance_type_override={"web": "t3.small"},
        tags={"huit_assetid": "12057"},
    )

    preview_config = resolve_environment_config(config, "pr-123", "prod")
    preview_override = preview_config.environment_overrides["pr-123"]

    assert preview_override.instance_type_override == "db.t4g.small"
    assert preview_override.ec2_instance_type_override == {"web": "t3.small"}
    assert preview_override.tags == {}
    assert "huit_assetid" not in preview_config.get_tags_for_environment("pr-123")


def test_dynamic_preview_requires_preview_from() -> None:
    with pytest.raises(SystemExit):
        resolve_environment_config(_config(), "pr-123")


def test_static_resolution_does_not_consume_preview_templates() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="sveltekit",
                environment_variables={
                    "DJANGO_INTERNAL_URL": "http://django.{service_discovery_namespace}:8000",
                },
            ),
        ],
        service_discovery=ServiceDiscoveryConfig(
            namespace_template="{project}-{env}.local"
        ),
        service_discovery_configured=True,
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.example.com",
        ),
    )

    prod_config = resolve_environment_config(config, "prod")
    preview_config = resolve_environment_config(config, "pr-123", "prod")

    assert prod_config.services[0].environment_variables["DJANGO_INTERNAL_URL"] == "http://django.demo-prod.local:8000"
    assert preview_config.services[0].environment_variables["DJANGO_INTERNAL_URL"] == "http://django.demo-pr-123.local:8000"


def test_preview_build_parameters_include_dns_and_tags() -> None:
    preview_config = resolve_environment_config(_config(), "pr-123", "prod")
    preview_config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.bta.darthcrimson.org",
        hosted_zone_name="darthcrimson.org",
        tags=preview_config.get_tags_for_environment("pr-123"),
    )

    params = {
        item["ParameterKey"]: item["ParameterValue"]
        for item in _build_parameters(preview_config, "pr-123", _lookups())
    }

    assert params["ClusterDomain"] == "pr-123.bta.darthcrimson.org"
    assert params["HostedZoneId"] == "ZHOSTED123"
    assert params["SharedAlbCanonicalHostedZoneId"] == "ZALB123"
    assert params["DefaultListenerPriority"] == "30000"
    assert params["ExtraTagEphemeralCleanupId"] == "demo-pr-123"
    assert params["ExtraTagHuitAssetid"] == ""


def test_listener_priority_resolution_allocates_preview_range(monkeypatch) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="shared-alb",
            domain="pr-123.example.com",
            default_target_service="web",
            path_rules=[
                AlbPathRule(
                    name="api",
                    path_pattern="/api/*",
                    target_service="web",
                )
            ],
        ),
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            listener_priority_start=30000,
            listener_priority_end=30005,
        ),
    )
    config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.example.com",
        hosted_zone_name=None,
        tags={},
    )
    monkeypatch.setattr(
        "darth_infra.cli.cfn._resolve_stack_owned_listener_rule_priorities_by_label",
        lambda *_: {},
    )

    default_priority, path_priorities = _resolve_listener_priorities(
        config,
        "pr-123",
        _FakeElbv2Rules(
            [
                {"Priority": "30000"},
                {"Priority": "30002"},
            ]
        ),
        "listener-arn",
    )

    assert default_priority == 30001
    assert path_priorities == {"api": 30003}


def test_listener_priority_resolution_reuses_stack_owned_by_rule(monkeypatch) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="shared-alb",
            domain="app.example.com",
            default_target_service="web",
            path_rules=[
                AlbPathRule(
                    name="api",
                    path_pattern="/api/*",
                    target_service="web",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "darth_infra.cli.cfn._resolve_stack_owned_listener_rule_priorities_by_label",
        lambda *_: {"default": 101, "api": 102},
    )

    default_priority, path_priorities = _resolve_listener_priorities(
        config,
        "prod",
        _FakeElbv2Rules([{"Priority": "101"}, {"Priority": "102"}]),
        "listener-arn",
    )

    assert default_priority == 101
    assert path_priorities == {"api": 102}


def test_listener_priority_resolution_rejects_configured_duplicates() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="shared-alb",
            domain="pr-123.example.com",
            default_target_service="web",
            default_listener_priority=100,
            path_rules=[
                AlbPathRule(
                    name="api",
                    path_pattern="/api/*",
                    target_service="web",
                    priority=30000,
                )
            ],
        ),
    )
    config.alb.default_listener_priority = 30000

    with pytest.raises(RuntimeError, match="Duplicate configured ALB listener priorities"):
        _resolve_listener_priorities(
            config,
            "pr-123",
            _FakeElbv2Rules(),
            "listener-arn",
        )


def test_preview_config_roundtrips_through_document(tmp_path: Path) -> None:
    """Preview config survives a document-preserving load/save round-trip.

    This replaces the old wizard-state round-trip: the Guided editor preserves
    the TOML document rather than reconstructing config from mutable state, so
    an unedited save must reproduce the same effective preview configuration.
    """
    path = tmp_path / "darth-infra.toml"
    path.write_text(dump_config(_config()))

    document = ProjectDocument.load(path)
    document.save()
    rebuilt = load_config(path)

    assert rebuilt.preview_environments.enabled is True
    assert rebuilt.preview_environments.domain_template == "pr-{number}.bta.darthcrimson.org"
    assert rebuilt.preview_environments.tags == {"ephemeral-cleanup-id": "{project}-{env}"}


def test_preview_service_discovery_names_are_isolated(tmp_path: Path) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(name="django", enable_service_discovery=True),
            ServiceConfig(
                name="sveltekit",
                environment_variables={
                    "DJANGO_INTERNAL_URL": "http://django.{service_discovery_namespace}:8000",
                },
            ),
        ],
        service_discovery=ServiceDiscoveryConfig(
            namespace_template="{project}-{env}.local"
        ),
        service_discovery_configured=True,
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.example.com",
        ),
    )

    preview_config = resolve_environment_config(config, "pr-123", "prod")
    templates = build_project_templates(preview_config)
    django_service = templates[
        "templates/generated/services/django.yaml"
    ].to_dict()
    sveltekit_service = templates[
        "templates/generated/services/sveltekit.yaml"
    ].to_dict()
    root = templates["templates/generated/root.yaml"].to_dict()

    assert (
        django_service["Resources"]["CloudMapService"]["Properties"]["Name"]
        == "django"
    )
    assert root["Resources"]["ServiceNamespace"]["Properties"]["Name"] == {
        "Fn::Sub": "${ProjectName}-${EnvironmentName}.local"
    }
    sveltekit_environment = sveltekit_service["Resources"]["TaskDefinition"][
        "Properties"
    ]["ContainerDefinitions"][0]["Environment"]
    assert {
        "Name": "DJANGO_INTERNAL_URL",
        "Value": "http://django.demo-pr-123.local:8000",
    } in sveltekit_environment


def test_preview_s3_overlay_renders_fallback_parameters_and_permissions(
    tmp_path: Path,
) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        s3_buckets=[
            S3BucketConfig(
                name="media",
                mode=S3BucketMode.SEED_COPY,
                seed_source_bucket_name="prod-media",
                preview_fallback_bucket_name="prod-media",
                preview_fallback_env_key="AWS_STORAGE_FALLBACK_BUCKET_NAME",
                connections=[
                    S3BucketConnection(
                        service="web",
                        env_key="AWS_STORAGE_BUCKET_NAME",
                    )
                ],
            )
        ],
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.example.com",
        ),
    )

    preview_config = resolve_environment_config(config, "pr-123", "prod")
    templates = build_project_templates(preview_config)
    root = templates["templates/generated/root.yaml"].to_dict()
    service = templates["templates/generated/services/web.yaml"].to_dict()

    service_parameters = root["Resources"]["ServiceWeb"]["Properties"][
        "Parameters"
    ]
    assert service_parameters["FallbackBucketNameMedia"] == "prod-media"
    assert service_parameters["FallbackBucketArnMedia"] == {
        "Fn::Sub": "arn:aws:s3:::prod-media"
    }
    environment = service["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]["Environment"]
    assert {
        "Name": "AWS_STORAGE_FALLBACK_BUCKET_NAME",
        "Value": {"Ref": "FallbackBucketNameMedia"},
    } in environment
    s3_policy = next(
        policy
        for policy in service["Resources"]["TaskRole"]["Properties"]["Policies"]
        if policy["PolicyName"] == "S3Access"
    )
    fallback_statement = next(
        statement
        for statement in s3_policy["PolicyDocument"]["Statement"]
        if {"Ref": "FallbackBucketArnMedia"} in statement["Resource"]
    )
    assert fallback_statement["Action"] == ["s3:GetObject", "s3:ListBucket"]


def test_preview_s3_overlay_derives_fallback_bucket_from_base_environment(
    tmp_path: Path,
) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        s3_buckets=[
            S3BucketConfig(
                name="media",
                mode=S3BucketMode.MANAGED,
                preview_fallback_env_key="AWS_STORAGE_FALLBACK_BUCKET_NAME",
                connections=[
                    S3BucketConnection(
                        service="web",
                        env_key="AWS_STORAGE_BUCKET_NAME",
                    )
                ],
            )
        ],
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.example.com",
        ),
    )

    preview_config = resolve_environment_config(config, "pr-123", "prod")
    templates = build_project_templates(preview_config)
    root = templates["templates/generated/root.yaml"].to_dict()
    service = templates["templates/generated/services/web.yaml"].to_dict()

    assert preview_config.s3_buckets[0].preview_fallback_bucket_name == "demo-prod-media"
    service_parameters = root["Resources"]["ServiceWeb"]["Properties"][
        "Parameters"
    ]
    assert service_parameters["FallbackBucketNameMedia"] == "demo-prod-media"
    assert service_parameters["FallbackBucketArnMedia"] == {
        "Fn::Sub": "arn:aws:s3:::demo-prod-media"
    }
    environment = service["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]["Environment"]
    assert any(
        entry["Name"] == "AWS_STORAGE_FALLBACK_BUCKET_NAME"
        for entry in environment
    )


def test_existing_preview_reuses_original_rds_snapshot(monkeypatch) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        rds=RdsConfig(database_name="app"),
        preview_environments=PreviewEnvironmentsConfig(
            enabled=True,
            base_environment="prod",
            name_pattern="pr-{number}",
            domain_template="pr-{number}.example.com",
        ),
    )
    config.active_preview = ActivePreviewEnvironment(
        env_name="pr-123",
        base_environment="prod",
        number="123",
        domain="pr-123.example.com",
        hosted_zone_name=None,
        tags={},
    )

    class FakeCloudFormation:
        def describe_stacks(self, *, StackName: str) -> dict[str, object]:
            assert StackName == "demo-ecs-pr-123"
            return {
                "Stacks": [
                    {
                        "Parameters": [
                            {
                                "ParameterKey": "RdsSnapshotIdentifier",
                                "ParameterValue": "rds:demo-prod-db-2026-05-22",
                            }
                        ]
                    }
                ]
            }

    class FakeRds:
        def describe_db_snapshots(self, **_: object) -> dict[str, object]:
            raise AssertionError("existing preview should not resolve latest snapshot")

    def fake_client(service: str, **_: object) -> object:
        if service == "cloudformation":
            return FakeCloudFormation()
        if service == "rds":
            return FakeRds()
        raise AssertionError(f"unexpected client: {service}")

    monkeypatch.setattr("darth_infra.cli.cfn.boto3.client", fake_client)

    assert _resolve_rds_snapshot(config, "pr-123") == "rds:demo-prod-db-2026-05-22"
