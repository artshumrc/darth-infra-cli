"""Unit tests for the injected AWS discovery/verification adapter (ticket 05).

These exercise the adapter interface in isolation: the deterministic fake used by
the editor's Pilot tests, the offline default, and the boto-backed production
adapter mapping fake boto responses to domain records and typed failures. Widget
behavior is covered by ``tests/test_tui_network_section.py``; here we only prove
the adapter contract so widgets never see raw boto dictionaries.
"""

from __future__ import annotations

from darth_infra.tui.editor.aws_discovery import (
    AwsDiscovery,
    BotoAwsDiscovery,
    DiscoveryKind,
    DiscoveryRequest,
    DiscoveryResult,
    FakeAwsDiscovery,
    OfflineAwsDiscovery,
    ResourceRecord,
    VerificationStatus,
)


# -- result state distinctions ----------------------------------------------


def test_discovery_result_distinguishes_success_empty_and_failure() -> None:
    success = DiscoveryResult.of([ResourceRecord("v", "V")])
    empty = DiscoveryResult.of([])
    failure = DiscoveryResult.failed("boom")

    assert success.ok and not success.empty and success.records
    assert empty.ok and empty.empty
    assert not failure.ok and failure.failure is not None
    assert failure.failure.message == "boom"


# -- fake adapter ------------------------------------------------------------


def test_fake_returns_configured_results_per_kind_and_records_requests() -> None:
    fake = FakeAwsDiscovery(
        results={
            DiscoveryKind.VPC_NAME: DiscoveryResult.of(
                [ResourceRecord("prod-vpc", "prod-vpc (vpc-1)", {"vpc_id": "vpc-1"})]
            ),
            DiscoveryKind.PRIVATE_SUBNETS: DiscoveryResult.of([]),
        }
    )

    vpc = fake.discover(DiscoveryRequest(DiscoveryKind.VPC_NAME))
    assert vpc.records[0].value == "prod-vpc"
    assert vpc.records[0].context["vpc_id"] == "vpc-1"

    subnets = fake.discover(
        DiscoveryRequest(DiscoveryKind.PRIVATE_SUBNETS, vpc_id="vpc-9")
    )
    assert subnets.empty
    # The parent context is recorded so callers can prove dependent filtering.
    assert fake.requests[-1].vpc_id == "vpc-9"


def test_fake_missing_kind_is_empty_success() -> None:
    fake = FakeAwsDiscovery()
    result = fake.discover(DiscoveryRequest(DiscoveryKind.LISTENER))
    assert result.ok and result.empty


def test_fake_verify_reports_verified_and_failed() -> None:
    fake = FakeAwsDiscovery(known={DiscoveryKind.LOAD_BALANCER: {"shared-alb"}})

    ok = fake.verify(DiscoveryRequest(DiscoveryKind.LOAD_BALANCER), "shared-alb")
    assert ok.status is VerificationStatus.VERIFIED

    bad = fake.verify(DiscoveryRequest(DiscoveryKind.LOAD_BALANCER), "missing")
    assert bad.status is VerificationStatus.FAILED
    assert "missing" in bad.message


def test_fake_satisfies_adapter_protocol() -> None:
    assert isinstance(FakeAwsDiscovery(), AwsDiscovery)
    assert isinstance(OfflineAwsDiscovery(), AwsDiscovery)
    assert isinstance(BotoAwsDiscovery("us-east-1"), AwsDiscovery)


# -- offline adapter ---------------------------------------------------------


def test_offline_adapter_fails_every_lookup_without_raising() -> None:
    offline = OfflineAwsDiscovery()
    result = offline.discover(DiscoveryRequest(DiscoveryKind.VPC_NAME))
    assert not result.ok
    assert "credentials" in result.failure.message.lower()

    outcome = offline.verify(DiscoveryRequest(DiscoveryKind.VPC_NAME), "x")
    assert outcome.status is VerificationStatus.FAILED


# -- boto adapter mapping (fake boto clients) --------------------------------


class _FakeEc2:
    def __init__(self) -> None:
        self.describe_vpcs_calls: list[dict] = []

    def describe_vpcs(self, **kwargs):
        self.describe_vpcs_calls.append(kwargs)
        if kwargs.get("Filters"):
            # tag:Name filter used by subnet resolution / verification.
            wanted = kwargs["Filters"][0]["Values"][0]
            if wanted == "prod":
                return {"Vpcs": [{"VpcId": "vpc-123", "CidrBlock": "10.0.0.0/16"}]}
            return {"Vpcs": []}
        return {
            "Vpcs": [
                {
                    "VpcId": "vpc-123",
                    "CidrBlock": "10.0.0.0/16",
                    "Tags": [{"Key": "Name", "Value": "prod"}],
                }
            ]
        }

    def describe_subnets(self, **kwargs):
        return {
            "Subnets": [
                {
                    "SubnetId": "subnet-priv",
                    "AvailabilityZone": "us-east-1a",
                    "CidrBlock": "10.0.1.0/24",
                    "MapPublicIpOnLaunch": False,
                    "Tags": [{"Key": "Name", "Value": "private-a"}],
                },
                {
                    "SubnetId": "subnet-pub",
                    "AvailabilityZone": "us-east-1a",
                    "CidrBlock": "10.0.2.0/24",
                    "MapPublicIpOnLaunch": True,
                },
            ]
        }


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self):
        return iter(self._pages)


class _FakeElbv2:
    def get_paginator(self, name):
        return _FakePaginator(
            [
                {
                    "LoadBalancers": [
                        {
                            "Type": "application",
                            "LoadBalancerName": "shared-alb",
                            "LoadBalancerArn": "arn:alb:1",
                            "Scheme": "internet-facing",
                            "DNSName": "shared.example.com",
                            "SecurityGroups": ["sg-abc"],
                        },
                        {"Type": "network", "LoadBalancerName": "nlb"},
                    ]
                }
            ]
        )

    def describe_listeners(self, **kwargs):
        return {
            "Listeners": [
                {
                    "ListenerArn": "arn:listener:443",
                    "Protocol": "HTTPS",
                    "Port": 443,
                }
            ]
        }

    def describe_load_balancers(self, **kwargs):
        return {
            "LoadBalancers": [
                {
                    "LoadBalancerName": "shared-alb",
                    "LoadBalancerArn": "arn:alb:1",
                    "SecurityGroups": ["sg-abc"],
                }
            ]
        }


def _boto(ec2=None, elbv2=None) -> BotoAwsDiscovery:
    ec2 = ec2 or _FakeEc2()
    elbv2 = elbv2 or _FakeElbv2()
    return BotoAwsDiscovery(
        "us-east-1",
        client_factory=lambda service: {"ec2": ec2, "elbv2": elbv2}[service],
    )


def test_boto_maps_vpcs_to_records_by_name_and_id() -> None:
    by_name = _boto().discover(DiscoveryRequest(DiscoveryKind.VPC_NAME))
    assert by_name.records[0].value == "prod"
    assert by_name.records[0].context["vpc_id"] == "vpc-123"

    by_id = _boto().discover(DiscoveryRequest(DiscoveryKind.VPC_ID))
    assert by_id.records[0].value == "vpc-123"


def test_boto_filters_subnets_by_public_private_and_needs_a_vpc() -> None:
    private = _boto().discover(
        DiscoveryRequest(DiscoveryKind.PRIVATE_SUBNETS, vpc_id="vpc-123")
    )
    assert [r.value for r in private.records] == ["subnet-priv"]

    public = _boto().discover(
        DiscoveryRequest(DiscoveryKind.PUBLIC_SUBNETS, vpc_id="vpc-123")
    )
    assert [r.value for r in public.records] == ["subnet-pub"]

    # Without a VPC, subnet discovery is a typed failure rather than an exception.
    missing = _boto().discover(DiscoveryRequest(DiscoveryKind.PRIVATE_SUBNETS))
    assert not missing.ok


def test_boto_load_balancers_skip_non_application_and_carry_arn() -> None:
    result = _boto().discover(DiscoveryRequest(DiscoveryKind.LOAD_BALANCER))
    assert [r.value for r in result.records] == ["shared-alb"]
    assert result.records[0].context["arn"] == "arn:alb:1"


def test_boto_listeners_require_a_parent_load_balancer() -> None:
    ok = _boto().discover(
        DiscoveryRequest(DiscoveryKind.LISTENER, load_balancer_arn="arn:alb:1")
    )
    assert ok.records[0].value == "arn:listener:443"

    missing = _boto().discover(DiscoveryRequest(DiscoveryKind.LISTENER))
    assert not missing.ok


def test_boto_turns_client_errors_into_typed_failures() -> None:
    class _Broken:
        def describe_vpcs(self, **kwargs):
            raise RuntimeError("no creds")

    result = _boto(ec2=_Broken()).discover(DiscoveryRequest(DiscoveryKind.VPC_NAME))
    assert not result.ok
    assert "no creds" in result.failure.message


def test_boto_verifies_vpc_and_load_balancer() -> None:
    ok = _boto().verify(DiscoveryRequest(DiscoveryKind.VPC_NAME), "prod")
    assert ok.status is VerificationStatus.VERIFIED

    bad = _boto().verify(DiscoveryRequest(DiscoveryKind.VPC_NAME), "nope")
    assert bad.status is VerificationStatus.FAILED
