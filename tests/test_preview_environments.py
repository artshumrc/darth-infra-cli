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
from darth_infra.scaffold.generator import generate_project
from darth_infra.tui.screens.review import build_config_from_state
from darth_infra.tui.wizard_export import project_config_to_wizard_state


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


def test_tui_roundtrips_preview_config() -> None:
    state = project_config_to_wizard_state(_config())
    rebuilt = build_config_from_state(state)

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
    output_dir = generate_project(preview_config, tmp_path / "out")

    django_service = (
        output_dir / "templates" / "generated" / "services" / "django.yaml"
    ).read_text()
    sveltekit_service = (
        output_dir / "templates" / "generated" / "services" / "sveltekit.yaml"
    ).read_text()
    root = (output_dir / "templates" / "generated" / "root.yaml").read_text()

    assert "Name: django" in django_service
    assert "Name: django-pr-123" not in django_service
    assert "Name: !Sub '${ProjectName}-${EnvironmentName}.local'" in root
    assert "Value: 'http://django.demo-pr-123.local:8000'" in sveltekit_service


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
    output_dir = generate_project(preview_config, tmp_path / "out")
    root = (output_dir / "templates" / "generated" / "root.yaml").read_text()
    service = (
        output_dir / "templates" / "generated" / "services" / "web.yaml"
    ).read_text()

    assert "        FallbackBucketNameMedia: 'prod-media'" in root
    assert "        FallbackBucketArnMedia: !Sub 'arn:aws:s3:::prod-media'" in root
    assert "AWS_STORAGE_FALLBACK_BUCKET_NAME" in service
    assert "Value: !Ref FallbackBucketNameMedia" in service
    fallback_statement = service.split("- !Ref FallbackBucketArnMedia", 1)[0].rsplit(
        "- Effect: Allow", 1
    )[1]
    assert "s3:GetObject" in fallback_statement
    assert "s3:ListBucket" in fallback_statement
    assert "s3:PutObject" not in fallback_statement
    assert "s3:DeleteObject" not in fallback_statement


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
    output_dir = generate_project(preview_config, tmp_path / "out")
    root = (output_dir / "templates" / "generated" / "root.yaml").read_text()
    service = (
        output_dir / "templates" / "generated" / "services" / "web.yaml"
    ).read_text()

    assert preview_config.s3_buckets[0].preview_fallback_bucket_name == "demo-prod-media"
    assert "        FallbackBucketNameMedia: 'demo-prod-media'" in root
    assert "        FallbackBucketArnMedia: !Sub 'arn:aws:s3:::demo-prod-media'" in root
    assert "AWS_STORAGE_FALLBACK_BUCKET_NAME" in service


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
