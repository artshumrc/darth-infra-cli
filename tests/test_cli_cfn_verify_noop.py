"""Unit tests for the structural ``--verify-noop`` release gate (mocked boto3).

These exercise ``verify_noop_structural`` — the same code path
``darth-infra deploy --verify-noop`` runs — against hand-rolled fake
CloudFormation clients and a stubbed template builder. The real-stack
acceptance criteria in ticket 11 require AWS credentials and are validated
against live stacks; these tests prove the comparison logic: parameter
resolution, condition evaluation, nested-stack recursion, and the GetAtt
fallback that avoids false positives on stable cross-references.
"""

from __future__ import annotations

from darth_infra.cli import cfn
from darth_infra.cli.cfn import ResolvedLookupData, verify_noop_structural
from darth_infra.config.models import ProjectConfig, ServiceConfig


class _Template:
    def __init__(self, body: dict) -> None:
        self._body = body

    def to_dict(self) -> dict:
        return self._body


class _Paginator:
    def __init__(self, nested: list[tuple[str, str]]) -> None:
        self._nested = nested

    def paginate(self, **_: object):
        return [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": lid,
                        "ResourceType": "AWS::CloudFormation::Stack",
                        "PhysicalResourceId": phys,
                    }
                    for lid, phys in self._nested
                ]
            }
        ]


class _FakeCloudFormation:
    """Fake CloudFormation client keyed by stack name/ARN."""

    def __init__(
        self,
        templates: dict[str, dict],
        params: dict[str, list[dict]],
        nested: list[tuple[str, str]],
    ) -> None:
        self._templates = templates
        self._params = params
        self._nested = nested

    def get_template(self, *, StackName: str, TemplateStage: str) -> dict:
        return {"TemplateBody": self._templates[StackName]}

    def describe_stacks(self, *, StackName: str) -> dict:
        return {"Stacks": [{"Parameters": self._params.get(StackName, [])}]}

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_stack_resources"
        return _Paginator(self._nested)


def _lookups() -> ResolvedLookupData:
    return ResolvedLookupData(
        vpc_id="vpc-1",
        vpc_cidr="10.0.0.0/16",
        private_subnet_ids=["subnet-1"],
        public_subnet_ids=["subnet-2"],
        shared_listener_arn="listener-arn",
        shared_alb_security_group_id="sg-1",
        shared_alb_dns_name="alb.example.com",
        shared_alb_canonical_hosted_zone_id="ZALB",
        hosted_zone_id="ZHZ",
        default_listener_priority=49991,
        path_rule_priorities={},
        rds_snapshot_identifier="",
        rds_source_secret_arn="",
        external_secret_arns={},
        existing_service_discovery_namespace_id="",
    )


def _config() -> ProjectConfig:
    return ProjectConfig(project_name="demo", services=[ServiceConfig(name="web")])


def _run(
    monkeypatch,
    *,
    generated: dict[str, dict],
    deployed_templates: dict[str, dict],
    deployed_params: dict[str, list[dict]],
    nested: list[tuple[str, str]],
    build_params: list[dict] | None = None,
) -> int:
    fake_cf = _FakeCloudFormation(deployed_templates, deployed_params, nested)
    monkeypatch.setattr(cfn.boto3, "client", lambda *a, **k: fake_cf)
    monkeypatch.setattr(
        "darth_infra.scaffold.builders.build_project_templates",
        lambda config: {k: _Template(v) for k, v in generated.items()},
    )
    monkeypatch.setattr(
        cfn,
        "_build_parameters",
        lambda config, env, lookups: build_params
        or [
            {"ParameterKey": "ProjectName", "ParameterValue": "demo"},
            {"ParameterKey": "EnvironmentName", "ParameterValue": "prod"},
            {"ParameterKey": "AlbMode", "ParameterValue": "shared"},
            {"ParameterKey": "DefaultListenerPriority", "ParameterValue": "49991"},
        ],
    )
    return verify_noop_structural(_config(), "prod", _lookups())


def test_identical_templates_pass(monkeypatch, capsys) -> None:
    root = {"Resources": {"Cluster": {"Type": "AWS::ECS::Cluster", "Properties": {}}}}
    rc = _run(
        monkeypatch,
        generated={"templates/generated/root.yaml": root},
        deployed_templates={"demo-ecs-prod": root},
        deployed_params={"demo-ecs-prod": []},
        nested=[],
    )
    assert rc == 0
    assert "structural no-op confirmed" in capsys.readouterr().out


def test_priority_literal_vs_resolved_ref_is_noop(monkeypatch) -> None:
    # Deployed hardcodes 49991; new refs a parameter that resolves to 49991.
    deployed_root = {
        "Resources": {
            "Rule": {
                "Type": "AWS::ElasticLoadBalancingV2::ListenerRule",
                "Properties": {"Priority": 49991},
            }
        }
    }
    gen_root = {
        "Resources": {
            "Rule": {
                "Type": "AWS::ElasticLoadBalancingV2::ListenerRule",
                "Properties": {"Priority": {"Ref": "DefaultListenerPriority"}},
            }
        }
    }
    rc = _run(
        monkeypatch,
        generated={"templates/generated/root.yaml": gen_root},
        deployed_templates={"demo-ecs-prod": deployed_root},
        deployed_params={"demo-ecs-prod": []},
        nested=[],
    )
    assert rc == 0


def test_condition_gated_off_resource_ignored(monkeypatch) -> None:
    # A dedicated-ALB listener exists in both templates but its condition is
    # false (shared ALB), so its Tags difference must not fail the gate.
    conditions = {"UseDedicatedAlb": {"Fn::Equals": [{"Ref": "AlbMode"}, "dedicated"]}}
    deployed_root = {
        "Conditions": conditions,
        "Resources": {
            "DedicatedListener": {
                "Type": "AWS::ElasticLoadBalancingV2::Listener",
                "Condition": "UseDedicatedAlb",
                "Properties": {"Tags": [{"Key": "Project", "Value": "demo"}]},
            }
        },
    }
    gen_root = {
        "Conditions": conditions,
        "Resources": {
            "DedicatedListener": {
                "Type": "AWS::ElasticLoadBalancingV2::Listener",
                "Condition": "UseDedicatedAlb",
                "Properties": {},
            }
        },
    }
    rc = _run(
        monkeypatch,
        generated={"templates/generated/root.yaml": gen_root},
        deployed_templates={"demo-ecs-prod": deployed_root},
        deployed_params={"demo-ecs-prod": [{"ParameterKey": "AlbMode", "ParameterValue": "shared"}]},
        nested=[],
    )
    assert rc == 0


def test_real_property_change_fails(monkeypatch, capsys) -> None:
    deployed_root = {
        "Resources": {
            "Svc": {"Type": "AWS::ECS::Service", "Properties": {"DesiredCount": 2}}
        }
    }
    gen_root = {
        "Resources": {
            "Svc": {"Type": "AWS::ECS::Service", "Properties": {"DesiredCount": 3}}
        }
    }
    rc = _run(
        monkeypatch,
        generated={"templates/generated/root.yaml": gen_root},
        deployed_templates={"demo-ecs-prod": deployed_root},
        deployed_params={"demo-ecs-prod": []},
        nested=[],
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "changed resource Svc" in out
    assert ".DesiredCount" in out


def test_nested_stack_getatt_param_no_false_positive(monkeypatch) -> None:
    # EcsService.Cluster = Ref(ClusterArn); root passes ClusterArn as a GetAtt.
    # Deployed child has the concrete ARN. The GetAtt fallback must treat this
    # as unchanged, and TemplateURL churn on the wrapper must be ignored.
    root = {
        "Resources": {
            "ServiceWeb": {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "services/web.yaml",
                    "Parameters": {"ClusterArn": {"Fn::GetAtt": ["Cluster", "Arn"]}},
                },
            }
        }
    }
    deployed_root = {
        "Resources": {
            "ServiceWeb": {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://s3/old-hash.template",
                    "Parameters": {"ClusterArn": "arn:aws:ecs:::cluster/demo-prod"},
                },
            }
        }
    }
    child = {
        "Resources": {
            "EcsService": {
                "Type": "AWS::ECS::Service",
                "Properties": {"Cluster": {"Ref": "ClusterArn"}},
            }
        }
    }
    rc = _run(
        monkeypatch,
        generated={
            "templates/generated/root.yaml": root,
            "templates/generated/services/web.yaml": child,
        },
        deployed_templates={
            "demo-ecs-prod": deployed_root,
            "web-phys": child,
        },
        deployed_params={
            "demo-ecs-prod": [],
            "web-phys": [
                {"ParameterKey": "ClusterArn", "ParameterValue": "arn:aws:ecs:::cluster/demo-prod"}
            ],
        },
        nested=[("ServiceWeb", "web-phys")],
    )
    assert rc == 0


def test_real_change_inside_nested_stack_fails(monkeypatch, capsys) -> None:
    root = {
        "Resources": {
            "ServiceWeb": {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {"TemplateURL": "services/web.yaml", "Parameters": {}},
            }
        }
    }
    deployed_child = {
        "Resources": {
            "TaskDefinition": {
                "Type": "AWS::ECS::TaskDefinition",
                "Properties": {"Cpu": "256"},
            }
        }
    }
    gen_child = {
        "Resources": {
            "TaskDefinition": {
                "Type": "AWS::ECS::TaskDefinition",
                "Properties": {"Cpu": "512"},
            }
        }
    }
    rc = _run(
        monkeypatch,
        generated={
            "templates/generated/root.yaml": root,
            "templates/generated/services/web.yaml": gen_child,
        },
        deployed_templates={"demo-ecs-prod": root, "web-phys": deployed_child},
        deployed_params={"demo-ecs-prod": [], "web-phys": []},
        nested=[("ServiceWeb", "web-phys")],
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "ServiceWeb" in out
    assert "TaskDefinition" in out
