from __future__ import annotations

from pathlib import Path

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    CloudFrontConnection,
    CloudFrontCookiesMode,
    CloudFrontQueryStringsMode,
    ProjectConfig,
    S3BucketConfig,
    S3BucketConnection,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates

from builders_expected import (
    CF_CUSTOM_DOMAIN,
    CF_DEDICATED_ALBCLOUDFRONT,
    CF_NO_CUSTOM_DOMAIN_ALBCLOUDFRONT,
    FULL_FEATURED_RESOURCES,
    FULL_FEATURED_SERVICE_PARAMETERS,
)
from builders_harness import assert_template_passes_cfn_lint, template_to_dict


def _config(
    *,
    custom_domain: str | None = "cdn.example.com",
    forward_auth: bool = False,
    dedicated: bool = False,
) -> ProjectConfig:
    alb = AlbConfig(
        mode=AlbMode.DEDICATED if dedicated else AlbMode.SHARED,
        certificate_arn=(
            "arn:aws:acm:us-east-1:123456789012:certificate/"
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
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
            "arn:aws:acm:us-east-1:123456789012:certificate/"
            "11111111-2222-3333-4444-555555555555"
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


def _full_featured_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.DEDICATED,
            certificate_arn=(
                "arn:aws:acm:us-east-1:123456789012:certificate/"
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            ),
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
        ),
        cloudfront=CloudFrontConfig(
            enabled=True,
            origin_https_only=True,
            custom_domain="cdn.example.com",
            certificate_arn=(
                "arn:aws:acm:us-east-1:123456789012:certificate/"
                "11111111-2222-3333-4444-555555555555"
            ),
            comment="demo cdn",
            connections=[CloudFrontConnection(service="web", env_key="CDN_URL")],
            cached_behaviors=[
                CloudFrontCachedBehavior(
                    name="iiif",
                    path_pattern="/iiif/*",
                    forward_authorization_header=True,
                    query_strings=CloudFrontQueryStringsMode.ALLOWLIST,
                    query_string_allowlist=["v", "page"],
                    cookies=CloudFrontCookiesMode.ALLOWLIST,
                    cookie_allowlist=["session"],
                    compress=False,
                ),
                CloudFrontCachedBehavior(name="assets", path_pattern="/assets/*"),
            ],
        ),
        s3_buckets=[
            S3BucketConfig(
                name="media-files",
                cloudfront=True,
                cors=True,
                connections=[
                    S3BucketConnection(
                        service="web",
                        env_key="MEDIA_BUCKET",
                        cloudfront_env_key="MEDIA_CDN",
                    )
                ],
            ),
        ],
    )


def _root(config: ProjectConfig) -> dict[str, object]:
    return template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )


def _alb_cf_default_headers(root: dict[str, object]) -> list[str]:
    behaviors = root["Resources"]["AlbCloudFront"]["Properties"][
        "DistributionConfig"
    ]["CacheBehaviors"]
    return behaviors[0]["ForwardedValues"]["Headers"]


def test_cached_behavior_always_forwards_host_header() -> None:
    root = _root(_config(forward_auth=False))

    assert _alb_cf_default_headers(root) == ["Host"]


def test_cached_behavior_can_also_forward_authorization() -> None:
    root = _root(_config(forward_auth=True))

    assert _alb_cf_default_headers(root) == ["Host", "Authorization"]


def test_alb_cloudfront_with_custom_domain_shared_alb() -> None:
    config = _config(custom_domain="cdn.example.com", forward_auth=True)
    root = _root(config)

    assert root["Resources"]["AlbCloudFront"] == CF_CUSTOM_DOMAIN["AlbCloudFront"]
    for output in (
        "CloudFrontDistributionId",
        "CloudFrontDomainName",
        "CloudFrontUrl",
    ):
        assert root["Outputs"][output] == CF_CUSTOM_DOMAIN["Outputs"][output]


def test_alb_cloudfront_without_custom_domain_has_no_aliases_or_cert() -> None:
    config = _config(custom_domain=None)
    root = _root(config)

    distribution_config = root["Resources"]["AlbCloudFront"]["Properties"][
        "DistributionConfig"
    ]
    assert "Aliases" not in distribution_config
    assert "ViewerCertificate" not in distribution_config
    assert root["Resources"]["AlbCloudFront"] == CF_NO_CUSTOM_DOMAIN_ALBCLOUDFRONT


def test_alb_cloudfront_dedicated_alb_origin() -> None:
    config = _config(dedicated=True)
    root = _root(config)

    assert root["Resources"]["AlbCloudFront"] == CF_DEDICATED_ALBCLOUDFRONT


def test_service_listener_hosts_include_cluster_domain_and_cf_domain() -> None:
    config = _config(custom_domain="cdn.example.com")
    service = template_to_dict(
        build_project_templates(config)["templates/generated/services/web.yaml"]
    )

    rule = service["Resources"]["DefaultHostHeaderRule"]["Properties"]
    host_values = rule["Conditions"][0]["HostHeaderConfig"]["Values"]
    assert host_values == [{"Ref": "ClusterDomain"}, "cdn.example.com"]


def test_full_featured_cloudfront_resources() -> None:
    config = _full_featured_config()
    root = _root(config)

    for logical_id in (
        "AlbCloudFront",
        "CloudFrontOacmediafiles",
        "CloudFrontmediafiles",
        "BucketPolicymediafiles",
    ):
        assert root["Resources"][logical_id] == FULL_FEATURED_RESOURCES[logical_id]

    behaviors = root["Resources"]["AlbCloudFront"]["Properties"][
        "DistributionConfig"
    ]["CacheBehaviors"]
    assert [behavior["PathPattern"] for behavior in behaviors] == [
        "/iiif/*",
        "/assets/*",
    ]


def test_full_featured_cloudfront_service_parameters() -> None:
    config = _full_featured_config()
    root = _root(config)

    built_parameters = root["Resources"]["ServiceWeb"]["Properties"][
        "Parameters"
    ]
    assert built_parameters == FULL_FEATURED_SERVICE_PARAMETERS
    assert built_parameters["CloudFrontUrlCDNURL"] == {
        "Fn::Sub": "https://${AlbCloudFront.DomainName}"
    }
    assert built_parameters["CloudFrontUrlMediaFiles"] == {
        "Fn::Sub": "https://${CloudFrontmediafiles.DomainName}"
    }


def test_full_featured_cloudfront_service_declares_params_and_env() -> None:
    """The service template must declare the CloudFront-URL parameters the root
    stack passes it and inject the matching env vars. Without this the nested
    stack receives undeclared parameters (deploy fails) and drops the CDN env
    vars. This guards the service side that the root-side parameter test misses.
    """
    config = _full_featured_config()
    service = template_to_dict(
        build_project_templates(config)["templates/generated/services/web.yaml"]
    )

    # Parameters the root passes (s3 cloudfront_env_key + ALB cloudfront) must
    # be declared on the child, or CloudFormation rejects the nested stack.
    assert service["Parameters"]["CloudFrontUrlMediaFiles"] == {"Type": "String"}
    assert service["Parameters"]["CloudFrontUrlCDNURL"] == {"Type": "String"}

    environment = service["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]["Environment"]
    env_by_name = {entry["Name"]: entry["Value"] for entry in environment}
    assert env_by_name["MEDIA_CDN"] == {"Ref": "CloudFrontUrlMediaFiles"}
    assert env_by_name["CDN_URL"] == {"Ref": "CloudFrontUrlCDNURL"}


def test_no_cloudfront_resources_when_disabled() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
    )
    root = _root(config)

    assert "AlbCloudFront" not in root["Resources"]
    assert "CloudFrontDistributionId" not in root["Outputs"]


def test_full_featured_cloudfront_root_passes_cfn_lint(tmp_path: Path) -> None:
    root = build_project_templates(_full_featured_config())[
        "templates/generated/root.yaml"
    ]

    assert_template_passes_cfn_lint(root, tmp_path / "root-cloudfront.yaml")
