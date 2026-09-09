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


def _origin_request_config(
    *, headers: list[str] | None = None, forward_auth: bool = False
) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
        ),
        cloudfront=CloudFrontConfig(
            enabled=True,
            origin_https_only=True,
            cached_behaviors=[
                CloudFrontCachedBehavior(
                    name="iiif",
                    path_pattern="/iiif/*",
                    origin_request_headers=headers
                    if headers is not None
                    else ["Referer"],
                    forward_authorization_header=forward_auth,
                    min_ttl_seconds=0,
                    default_ttl_seconds=3600,
                    max_ttl_seconds=31536000,
                ),
                CloudFrontCachedBehavior(name="assets", path_pattern="/assets/*"),
            ],
        ),
    )


def _cache_behaviors(root: dict[str, object]) -> list[dict[str, object]]:
    return root["Resources"]["AlbCloudFront"]["Properties"]["DistributionConfig"][
        "CacheBehaviors"
    ]


def test_origin_request_headers_emit_a_cache_and_origin_request_policy() -> None:
    root = _root(_origin_request_config())

    cache_policy = root["Resources"]["CloudFrontCachePolicyIiif"]
    origin_policy = root["Resources"]["CloudFrontOriginRequestPolicyIiif"]

    assert cache_policy["Type"] == "AWS::CloudFront::CachePolicy"
    assert origin_policy["Type"] == "AWS::CloudFront::OriginRequestPolicy"
    assert origin_policy["Properties"]["OriginRequestPolicyConfig"][
        "HeadersConfig"
    ] == {"HeaderBehavior": "whitelist", "Headers": ["Referer"]}


def test_forwarded_header_stays_out_of_the_cache_key() -> None:
    """The whole point of the policy pair: the origin sees Referer, but two
    projects requesting the same object still share one cache entry.
    """
    root = _root(_origin_request_config())

    parameters = root["Resources"]["CloudFrontCachePolicyIiif"]["Properties"][
        "CachePolicyConfig"
    ]["ParametersInCacheKeyAndForwardedToOrigin"]

    assert parameters["HeadersConfig"] == {
        "HeaderBehavior": "whitelist",
        "Headers": ["Host"],
    }


def test_cache_policy_still_keys_on_authorization_when_configured() -> None:
    root = _root(_origin_request_config(forward_auth=True))

    parameters = root["Resources"]["CloudFrontCachePolicyIiif"]["Properties"][
        "CachePolicyConfig"
    ]["ParametersInCacheKeyAndForwardedToOrigin"]

    assert parameters["HeadersConfig"]["Headers"] == ["Host", "Authorization"]


def test_cache_policy_carries_the_behavior_ttls_and_query_strings() -> None:
    root = _root(_origin_request_config())

    config = root["Resources"]["CloudFrontCachePolicyIiif"]["Properties"][
        "CachePolicyConfig"
    ]

    assert (config["MinTTL"], config["DefaultTTL"], config["MaxTTL"]) == (
        0,
        3600,
        31536000,
    )
    assert config["ParametersInCacheKeyAndForwardedToOrigin"][
        "QueryStringsConfig"
    ] == {"QueryStringBehavior": "all"}


def test_policy_behavior_drops_forwarded_values_and_inline_ttls() -> None:
    """CloudFormation rejects a cache behavior that sets both a cache policy and
    the legacy fields.
    """
    behavior = _cache_behaviors(_root(_origin_request_config()))[0]

    assert behavior["CachePolicyId"] == {"Ref": "CloudFrontCachePolicyIiif"}
    assert behavior["OriginRequestPolicyId"] == {
        "Ref": "CloudFrontOriginRequestPolicyIiif"
    }
    for key in ("ForwardedValues", "MinTTL", "DefaultTTL", "MaxTTL"):
        assert key not in behavior


def test_behaviors_without_origin_request_headers_keep_forwarded_values() -> None:
    root = _root(_origin_request_config())
    behavior = _cache_behaviors(root)[1]

    assert behavior["PathPattern"] == "/assets/*"
    assert behavior["ForwardedValues"]["Headers"] == ["Host"]
    assert "CachePolicyId" not in behavior
    assert "CloudFrontCachePolicyAssets" not in root["Resources"]


def test_no_policies_without_origin_request_headers() -> None:
    root = _root(_origin_request_config(headers=[]))

    assert "CloudFrontCachePolicyIiif" not in root["Resources"]
    assert "CloudFrontOriginRequestPolicyIiif" not in root["Resources"]
    assert "ForwardedValues" in _cache_behaviors(root)[0]


def test_origin_request_policy_root_passes_cfn_lint(tmp_path: Path) -> None:
    root = build_project_templates(_origin_request_config())[
        "templates/generated/root.yaml"
    ]

    assert_template_passes_cfn_lint(root, tmp_path / "root-origin-request.yaml")
