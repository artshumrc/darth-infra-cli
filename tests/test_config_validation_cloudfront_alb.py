from __future__ import annotations

import pytest

from darth_infra.config.loader import dump_config, load_config

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


def test_alb_listener_priorities_are_optional() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[_base_service()],
        alb=AlbConfig(
            domain="app.example.com",
            default_target_service="web",
        ),
    )

    assert config.alb.default_listener_priority is None


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


def _with_origin_request_headers(
    headers: list[str], **behavior_kwargs: object
) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[_base_service()],
        alb=_base_alb(),
        cloudfront=CloudFrontConfig(
            enabled=True,
            cached_behaviors=[
                CloudFrontCachedBehavior(
                    name="images",
                    path_pattern="/images/*",
                    origin_request_headers=headers,
                    **behavior_kwargs,
                )
            ],
        ),
    )


def test_origin_request_headers_accepts_a_viewer_header() -> None:
    config = _with_origin_request_headers(["Referer"])

    assert config.cloudfront.cached_behaviors[0].origin_request_headers == ["Referer"]


def test_origin_request_headers_rejects_host() -> None:
    with pytest.raises(ValueError, match="it is always forwarded to the origin"):
        _with_origin_request_headers(["Host"])


def test_origin_request_headers_rejects_authorization() -> None:
    with pytest.raises(ValueError, match="use forward_authorization_header instead"):
        _with_origin_request_headers(["Authorization"])


def test_origin_request_headers_rejects_accept_encoding_when_compressed() -> None:
    with pytest.raises(ValueError, match="normalizes it into the cache key"):
        _with_origin_request_headers(["Accept-Encoding"])


def test_origin_request_headers_allows_accept_encoding_without_compression() -> None:
    config = _with_origin_request_headers(["Accept-Encoding"], compress=False)

    assert config.cloudfront.cached_behaviors[0].origin_request_headers == [
        "Accept-Encoding"
    ]


def test_origin_request_headers_rejects_case_insensitive_duplicates() -> None:
    with pytest.raises(ValueError, match="Duplicate cloudfront.cached_behaviors"):
        _with_origin_request_headers(["Referer", "referer"])


def test_origin_request_headers_rejects_a_malformed_header_name() -> None:
    with pytest.raises(ValueError, match="is not a valid HTTP header name"):
        _with_origin_request_headers(["X Real IP"])


def test_allowed_referers_accepts_hostnames() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[_base_service()],
        alb=_base_alb(),
        cloudfront=_base_cloudfront(allowed_referers=["harvard.edu", "Example.org"]),
    )

    assert config.cloudfront.allowed_referers == ["harvard.edu", "Example.org"]


@pytest.mark.parametrize(
    "referer",
    ["https://harvard.edu", "harvard.edu/path", "harvard.edu:443", "*.harvard.edu", ""],
)
def test_allowed_referers_rejects_anything_but_a_hostname(referer: str) -> None:
    with pytest.raises(ValueError, match="must be a hostname"):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=_base_cloudfront(allowed_referers=[referer]),
        )


def test_allowed_referers_rejects_case_insensitive_duplicates() -> None:
    with pytest.raises(ValueError, match="Duplicate cloudfront.allowed_referers"):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=_base_cloudfront(allowed_referers=["harvard.edu", "Harvard.edu"]),
        )


def test_allowed_referers_require_cloudfront_enabled() -> None:
    with pytest.raises(ValueError, match="require cloudfront.enabled=true"):
        ProjectConfig(
            project_name="demo",
            services=[_base_service()],
            alb=_base_alb(),
            cloudfront=CloudFrontConfig(allowed_referers=["harvard.edu"]),
        )


def test_allowed_referers_round_trip_through_toml(tmp_path) -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[_base_service()],
        alb=_base_alb(),
        cloudfront=_base_cloudfront(allowed_referers=["harvard.edu"]),
    )
    path = tmp_path / "darth-infra.toml"
    path.write_text(dump_config(config))

    assert load_config(path).cloudfront.allowed_referers == ["harvard.edu"]
