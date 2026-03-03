from __future__ import annotations

import pytest

from darth_infra.cli.cfn import _resolve_shared_alb
from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    CloudFrontCachedBehavior,
    CloudFrontConfig,
    ProjectConfig,
    ServiceConfig,
)


class FakeElbv2:
    def __init__(self, listeners: list[dict[str, object]]) -> None:
        self.listeners = listeners

    def describe_load_balancers(
        self, *, Names: list[str] | None = None, LoadBalancerArns: list[str] | None = None
    ) -> dict[str, list[dict[str, object]]]:
        if Names:
            return {
                "LoadBalancers": [
                    {
                        "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/shared/abc",
                        "SecurityGroups": ["sg-1234abcd"],
                        "DNSName": "shared-alb-123.us-east-1.elb.amazonaws.com",
                    }
                ]
            }
        if LoadBalancerArns:
            return {
                "LoadBalancers": [
                    {"DNSName": "shared-alb-123.us-east-1.elb.amazonaws.com"}
                ]
            }
        raise AssertionError("unexpected describe_load_balancers call")

    def describe_listeners(
        self, *, LoadBalancerArn: str | None = None, ListenerArns: list[str] | None = None
    ) -> dict[str, list[dict[str, object]]]:
        if LoadBalancerArn:
            return {"Listeners": self.listeners}
        if ListenerArns:
            return {
                "Listeners": [
                    {
                        "ListenerArn": ListenerArns[0],
                        "Protocol": self.listeners[0]["Protocol"],
                        "Port": self.listeners[0]["Port"],
                        "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/shared/abc",
                    }
                ]
            }
        raise AssertionError("unexpected describe_listeners call")


def _config(*, listener_arn: str | None = None) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.SHARED,
            shared_alb_name="shared-alb",
            shared_listener_arn=listener_arn,
            shared_alb_security_group_id="sg-1234abcd" if listener_arn else None,
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
        ),
        cloudfront=CloudFrontConfig(
            enabled=True,
            origin_https_only=True,
            cached_behaviors=[
                CloudFrontCachedBehavior(name="iiif", path_pattern="/iiif/*")
            ],
        ),
    )


def test_resolve_shared_alb_rejects_non_https_listener_for_https_only_origin() -> None:
    config = _config()
    elbv2 = FakeElbv2(
        listeners=[{"ListenerArn": "arn:listener/http", "Protocol": "HTTP", "Port": 80}]
    )
    with pytest.raises(
        RuntimeError,
        match="requires a shared ALB HTTPS listener on port 443",
    ):
        _resolve_shared_alb(config, elbv2)


def test_resolve_shared_alb_prefers_https_443_for_https_only_origin() -> None:
    config = _config()
    listener_arn, sg_id, dns_name = _resolve_shared_alb(
        config,
        FakeElbv2(
            listeners=[
                {"ListenerArn": "arn:listener/http", "Protocol": "HTTP", "Port": 80},
                {"ListenerArn": "arn:listener/https", "Protocol": "HTTPS", "Port": 443},
            ]
        ),
    )
    assert listener_arn == "arn:listener/https"
    assert sg_id == "sg-1234abcd"
    assert dns_name == "shared-alb-123.us-east-1.elb.amazonaws.com"


def test_explicit_shared_listener_must_be_https_443_for_https_only_origin() -> None:
    config = _config(listener_arn="arn:listener/http-explicit")
    with pytest.raises(
        RuntimeError,
        match="requires shared ALB listener HTTPS:443",
    ):
        _resolve_shared_alb(
            config,
            FakeElbv2(
                listeners=[
                    {
                        "ListenerArn": "arn:listener/http-explicit",
                        "Protocol": "HTTP",
                        "Port": 80,
                    }
                ]
            ),
        )
