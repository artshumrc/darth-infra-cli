from __future__ import annotations

from darth_infra.cli.cfn import ResolvedLookupData, _build_parameters
from darth_infra.config.models import EnvironmentOverride, ProjectConfig, ServiceConfig


def test_build_parameters_uses_environment_specific_tag_values() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        tags={"owner": "platform", "cost-center": "shared"},
        environment_overrides={
            "dev": EnvironmentOverride(tags={"cost-center": "dev", "tier": "sandbox"})
        },
    )
    lookups = ResolvedLookupData(
        vpc_id="vpc-12345678",
        vpc_cidr="10.0.0.0/16",
        private_subnet_ids=["subnet-11111111"],
        public_subnet_ids=["subnet-22222222"],
        shared_listener_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/shared/abc/def",
        shared_alb_security_group_id="sg-12345678",
        shared_alb_dns_name="shared.example.com",
        default_listener_priority=None,
        path_rule_priorities={},
        rds_snapshot_identifier="",
        external_secret_arns={},
        existing_service_discovery_namespace_id="",
    )

    params = {
        item["ParameterKey"]: item["ParameterValue"]
        for item in _build_parameters(config, "dev", lookups)
    }

    assert params["ExtraTagOwner"] == "platform"
    assert params["ExtraTagCostCenter"] == "dev"
    assert params["ExtraTagTier"] == "sandbox"
