from __future__ import annotations

import pytest

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    ProjectConfig,
    ServiceConfig,
)


def _base_service() -> ServiceConfig:
    return ServiceConfig(name="web", port=8000)


def _base_alb(*, mode: AlbMode = AlbMode.SHARED, certificate_arn: str | None = None) -> AlbConfig:
    return AlbConfig(
        mode=mode,
        certificate_arn=certificate_arn,
        domain="app.example.com",
        default_target_service="web",
        default_listener_priority=100,
    )


def _base_cloudfront(**kwargs: object) -> CloudFrontConfig:
    return CloudFrontConfig(
        enabled=True,
        cached_behaviors=[
            CloudFrontCachedBehavior(name="images", path_pattern="/images/*")
        ],
        **kwargs,
    )


def test_custom_domain_requires_certificate() -> None:
    with pytest.raises(
        ValueError,
        match="cloudfront.custom_domain and cloudfront.certificate_arn must be set together",
    ):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=_base_cloudfront(custom_domain="cdn.example.com"),
        )


def test_custom_domain_must_be_host_only() -> None:
    with pytest.raises(
        ValueError,
        match="cloudfront.custom_domain must be a hostname without scheme/path",
    ):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=_base_cloudfront(
                custom_domain="https://cdn.example.com/path",
                certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555",
            ),
        )


def test_cloudfront_disabled_rejects_cloudfront_only_fields() -> None:
    with pytest.raises(
        ValueError,
        match="require cloudfront.enabled=true",
    ):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=CloudFrontConfig(origin_https_only=True),
        )


def test_dedicated_mode_origin_https_only_requires_alb_certificate() -> None:
    with pytest.raises(
        ValueError,
        match="cloudfront.origin_https_only requires alb.certificate_arn when alb.mode='dedicated'",
    ):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(mode=AlbMode.DEDICATED, certificate_arn=None),
            cloudfront=_base_cloudfront(origin_https_only=True),
        )
