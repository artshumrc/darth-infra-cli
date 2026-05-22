from __future__ import annotations

from pathlib import Path

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    EnvironmentOverride,
    LaunchType,
    ProjectConfig,
    ServiceDiscoveryConfig,
    ServiceConfig,
)
from darth_infra.scaffold.generator import generate_project


def _config(
    *,
    custom_domain: str | None = "cdn.example.com",
    forward_auth: bool = False,
    dedicated: bool = False,
) -> ProjectConfig:
    alb = AlbConfig(
        mode=AlbMode.DEDICATED if dedicated else AlbMode.SHARED,
        certificate_arn=(
            "arn:aws:acm:us-east-1:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            if dedicated
            else None
        ),
        domain="app.example.com",
        default_target_service="web",
        default_listener_priority=100,
    )
    cloudfront = CloudFrontConfig(
        enabled=True,
        origin_https_only=True,
        custom_domain=custom_domain,
        certificate_arn=(
            "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
            if custom_domain
            else None
        ),
        cached_behaviors=[
            CloudFrontCachedBehavior(
                name="iiif",
                path_pattern="/iiif/*",
                forward_authorization_header=forward_auth,
            )
        ],
    )
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=alb,
        cloudfront=cloudfront,
    )


def _read(output_dir: Path, relative: str) -> str:
    return (output_dir / relative).read_text()


def test_cached_behavior_always_forwards_host_header(tmp_path: Path) -> None:
    output_dir = generate_project(_config(forward_auth=False), tmp_path / "out")
    root = _read(output_dir, "templates/generated/root.yaml")
    assert "Headers:\n                - Host" in root


def test_cached_behavior_can_also_forward_authorization(tmp_path: Path) -> None:
    output_dir = generate_project(_config(forward_auth=True), tmp_path / "out")
    root = _read(output_dir, "templates/generated/root.yaml")
    assert "Headers:\n                - Host\n                - Authorization" in root


def test_service_listener_hosts_include_cluster_domain_and_cf_domain(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(
        _config(custom_domain="cdn.example.com"), tmp_path / "out"
    )
    service = _read(output_dir, "templates/generated/services/web.yaml")
    assert "- !Ref ClusterDomain" in service
    assert "- 'cdn.example.com'" in service


def test_dedicated_mode_with_certificate_emits_https_listener_and_redirect(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(_config(dedicated=True), tmp_path / "out")
    root = _read(output_dir, "templates/generated/root.yaml")
    assert "DedicatedAlbHttpsListener:" in root
    assert "Protocol: HTTPS" in root
    assert "RedirectConfig:" in root
    assert "Port: '443'" in root


def test_environment_tag_parameters_are_rendered_for_root_and_nested_stacks(
    tmp_path: Path,
) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        tags={"owner": "platform"},
        environment_overrides={
            "dev": EnvironmentOverride(tags={"cost-center": "dev-sandbox"})
        },
    )

    output_dir = generate_project(config, tmp_path / "out")
    root = _read(output_dir, "templates/generated/root.yaml")
    service = _read(output_dir, "templates/generated/services/web.yaml")

    assert "ExtraTagOwner:" in root
    assert "ExtraTagCostCenter:" in root
    assert "HasExtraTagCostCenter:" in root
    assert "ExtraTagCostCenter: !Ref ExtraTagCostCenter" in root
    assert "ExtraTagCostCenter:" in service
    assert "HasExtraTagCostCenter:" in service


def test_managed_ecr_repositories_are_empty_on_delete(tmp_path: Path) -> None:
    output_dir = generate_project(
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web", port=8000)],
        ),
        tmp_path / "out",
    )
    root = _read(output_dir, "templates/generated/root.yaml")

    assert "EcrRepoWeb:" in root
    assert "EmptyOnDelete: true" in root


def test_ec2_launch_resources_receive_cleanup_tags(tmp_path: Path) -> None:
    output_dir = generate_project(
        ProjectConfig(
            project_name="demo",
            services=[
                ServiceConfig(
                    name="worker",
                    launch_type=LaunchType.EC2,
                    ec2_instance_type="t3.medium",
                )
            ],
            tags={"ephemeral-cleanup-id": "demo-pr-123"},
        ),
        tmp_path / "out",
    )
    service = _read(output_dir, "templates/generated/services/worker.yaml")

    assert "Ec2InstanceProfile:" in service
    assert "LaunchTemplate:" in service
    assert "ResourceType: launch-template" in service
    assert "ExtraTagEphemeralCleanupId" in service


def test_service_discovery_namespace_defaults_to_legacy_local(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web", enable_service_discovery=True)],
        ),
        tmp_path / "out",
    )
    root = _read(output_dir, "templates/generated/root.yaml")

    assert "Name: !Sub 'local'" in root


def test_service_discovery_namespace_uses_configured_template(
    tmp_path: Path,
) -> None:
    output_dir = generate_project(
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web", enable_service_discovery=True)],
            service_discovery=ServiceDiscoveryConfig(
                namespace_template="{project}-{env}.local"
            ),
            service_discovery_configured=True,
        ),
        tmp_path / "out",
    )
    root = _read(output_dir, "templates/generated/root.yaml")

    assert "Name: !Sub '${ProjectName}-${EnvironmentName}.local'" in root


def test_listener_rules_do_not_emit_unsupported_tags(tmp_path: Path) -> None:
    output_dir = generate_project(_config(custom_domain=None), tmp_path / "out")
    service = _read(output_dir, "templates/generated/services/web.yaml")
    rule_block = service.split("DefaultHostHeaderRule:", 1)[1].split("EcsService:", 1)[0]

    assert "Type: AWS::ElasticLoadBalancingV2::ListenerRule" in rule_block
    assert "Tags:" not in rule_block


def test_rds_deletion_policy_snapshots_only_prod(tmp_path: Path) -> None:
    from darth_infra.config.models import RdsConfig

    output_dir = generate_project(
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web", port=8000)],
            rds=RdsConfig(database_name="demo", expose_to=["web"]),
        ),
        tmp_path / "out",
    )
    root = _read(output_dir, "templates/generated/root.yaml")

    assert "DeletionPolicy: !If [IsProd, Snapshot, Delete]" in root
    assert "UpdateReplacePolicy: !If [IsProd, Snapshot, Delete]" in root
