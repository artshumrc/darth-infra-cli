from __future__ import annotations

from pathlib import Path

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    ProjectConfig,
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
    output_dir = generate_project(_config(custom_domain="cdn.example.com"), tmp_path / "out")
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
