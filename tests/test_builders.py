from pathlib import Path

from cfn_flip import load_yaml
from jinja2 import Environment, FileSystemLoader

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    AlbPathRule,
    EnvironmentOverride,
    ProjectConfig,
    RdsConfig,
    SecretConfig,
    SecretSource,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates
from darth_infra.scaffold.generator import TEMPLATES_DIR, _build_context

from builders_harness import assert_template_passes_cfn_lint, template_to_dict


_BASE_TAG_PARAMETERS = (
    ("environment-type", "ExtraTagEnvironmentType", "HasExtraTagEnvironmentType"),
    (
        "ephemeral-cleanup-id",
        "ExtraTagEphemeralCleanupId",
        "HasExtraTagEphemeralCleanupId",
    ),
    (
        "preview-base-environment",
        "ExtraTagPreviewBaseEnvironment",
        "HasExtraTagPreviewBaseEnvironment",
    ),
    ("pull-request", "ExtraTagPullRequest", "HasExtraTagPullRequest"),
)


def _expected_tags() -> list[dict[str, object]]:
    tags: list[dict[str, object]] = [
        {"Key": "Project", "Value": {"Ref": "ProjectName"}},
        {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
    ]
    tags.extend(
        {
            "Fn::If": [
                condition_name,
                {"Key": key, "Value": {"Ref": parameter_name}},
                {"Ref": "AWS::NoValue"},
            ]
        }
        for key, parameter_name, condition_name in _BASE_TAG_PARAMETERS
    )
    return tags


def _config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
    )


def _shared_alb_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
            path_rules=[
                AlbPathRule(
                    name="api-v2",
                    path_pattern="/api/v2/*",
                    target_service="web",
                    priority=110,
                )
            ],
        ),
    )


def _dedicated_alb_config(*, certificate: bool = True) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        alb=AlbConfig(
            mode=AlbMode.DEDICATED,
            certificate_arn=(
                "arn:aws:acm:us-east-1:123456789012:certificate/"
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                if certificate
                else None
            ),
            domain="app.example.com",
            default_target_service="web",
            default_listener_priority=100,
        ),
    )


def _jinja_root_to_dict(config: ProjectConfig) -> dict[str, object]:
    context = _build_context(config)
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = environment.get_template("root.yaml.j2").render(**context)
    return dict(load_yaml(rendered))


def _jinja_service_to_dict(config: ProjectConfig) -> dict[str, object]:
    context = _build_context(config)
    service_context = context["services_ctx"][0]
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = environment.get_template("nested/service.yaml.j2").render(
        **{**context, **service_context}
    )
    return dict(load_yaml(rendered))


def test_builders_create_minimal_root_stack_core() -> None:
    templates = build_project_templates(_config())

    assert set(templates) == {
        "templates/generated/root.yaml",
        "templates/generated/services/web.yaml",
    }
    root = template_to_dict(templates["templates/generated/root.yaml"])

    assert root["AWSTemplateFormatVersion"] == "2010-09-09"
    assert root["Description"] == "darth-infra root stack for demo"
    assert root["Parameters"] == {
        "ProjectName": {"Type": "String", "Default": "demo"},
        "EnvironmentName": {"Type": "String"},
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "VpcCidr": {"Type": "String"},
        "PrivateSubnetIds": {"Type": "CommaDelimitedList"},
        "PublicSubnetIds": {"Type": "CommaDelimitedList"},
        "AlbMode": {
            "Type": "String",
            "AllowedValues": ["shared", "dedicated"],
            "Default": "shared",
        },
        "SharedAlbListenerArn": {"Type": "String", "Default": ""},
        "SharedAlbSecurityGroupId": {"Type": "String", "Default": ""},
        "SharedAlbDnsName": {"Type": "String", "Default": ""},
        "SharedAlbCanonicalHostedZoneId": {"Type": "String", "Default": ""},
        "HostedZoneId": {"Type": "String", "Default": ""},
        "CertificateArn": {"Type": "String", "Default": ""},
        "ClusterDomain": {"Type": "String", "Default": ""},
        **{
            parameter_name: {"Type": "String", "Default": ""}
            for _, parameter_name, _ in _BASE_TAG_PARAMETERS
        },
    }
    assert root["Conditions"] == {
        "IsProd": {"Fn::Equals": [{"Ref": "EnvironmentName"}, "prod"]},
        "UseDedicatedAlb": {"Fn::Equals": [{"Ref": "AlbMode"}, "dedicated"]},
        "HasCertificate": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "CertificateArn"}, ""]}]
        },
        "HasHostedZone": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "HostedZoneId"}, ""]}]
        },
        "UseDedicatedAlbWithCert": {
            "Fn::And": [
                {"Condition": "UseDedicatedAlb"},
                {"Condition": "HasCertificate"},
            ]
        },
        "UseDedicatedAlbNoCert": {
            "Fn::And": [
                {"Condition": "UseDedicatedAlb"},
                {"Fn::Not": [{"Condition": "HasCertificate"}]},
            ]
        },
        **{
            condition_name: {
                "Fn::Not": [
                    {"Fn::Equals": [{"Ref": parameter_name}, ""]}
                ]
            }
            for _, parameter_name, condition_name in _BASE_TAG_PARAMETERS
        },
    }

    resources = root["Resources"]
    assert set(resources) == {
        "EcsCluster",
        "DedicatedAlb",
        "DedicatedAlbSecurityGroup",
        "DedicatedAlbHttpListener",
        "DedicatedAlbHttpsListener",
        "EcrRepoWeb",
        "ServiceWeb",
        "DnsRecord",
        "CustomOverrides",
    }
    assert resources["EcsCluster"] == {
        "Type": "AWS::ECS::Cluster",
        "Properties": {
            "ClusterName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}"},
            "ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}],
            "Tags": _expected_tags(),
        },
    }
    assert resources["EcrRepoWeb"] == {
        "Type": "AWS::ECR::Repository",
        "Properties": {
            "RepositoryName": {
                "Fn::Sub": "${ProjectName}/${EnvironmentName}/web"
            },
            "EmptyOnDelete": True,
            "Tags": _expected_tags(),
        },
    }
    assert resources["ServiceWeb"] == {
        "Type": "AWS::CloudFormation::Stack",
        "DependsOn": "EcrRepoWeb",
        "Properties": {
            "TemplateURL": "services/web.yaml",
            "Parameters": {
                "ProjectName": {"Ref": "ProjectName"},
                "EnvironmentName": {"Ref": "EnvironmentName"},
                "VpcId": {"Ref": "VpcId"},
                "VpcCidr": {"Ref": "VpcCidr"},
                "PrivateSubnetIds": {
                    "Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]
                },
                "ClusterName": {"Ref": "EcsCluster"},
                "ClusterArn": {"Fn::GetAtt": ["EcsCluster", "Arn"]},
                "ClusterDomain": {"Ref": "ClusterDomain"},
                "AlbListenerArn": {
                    "Fn::If": [
                        "UseDedicatedAlb",
                        {
                            "Fn::If": [
                                "UseDedicatedAlbWithCert",
                                {"Ref": "DedicatedAlbHttpsListener"},
                                {"Ref": "DedicatedAlbHttpListener"},
                            ]
                        },
                        {"Ref": "SharedAlbListenerArn"},
                    ]
                },
                "AlbSecurityGroupId": {
                    "Fn::If": [
                        "UseDedicatedAlb",
                        {"Ref": "DedicatedAlbSecurityGroup"},
                        {"Ref": "SharedAlbSecurityGroupId"},
                    ]
                },
                **{
                    parameter_name: {"Ref": parameter_name}
                    for _, parameter_name, _ in _BASE_TAG_PARAMETERS
                },
            },
            "Tags": _expected_tags(),
        },
    }
    assert resources["CustomOverrides"] == {
        "Type": "AWS::CloudFormation::Stack",
        "Properties": {
            "TemplateURL": "../custom/overrides.yaml",
            "Tags": _expected_tags(),
        },
    }
    assert root["Outputs"] == {
        "ClusterName": {"Value": {"Ref": "EcsCluster"}},
        "StackEnvironment": {"Value": {"Ref": "EnvironmentName"}},
        "AlbListenerArn": {
            "Value": {
                "Fn::If": [
                    "UseDedicatedAlb",
                    {
                        "Fn::If": [
                            "UseDedicatedAlbWithCert",
                            {"Ref": "DedicatedAlbHttpsListener"},
                            {"Ref": "DedicatedAlbHttpListener"},
                        ]
                    },
                    {"Ref": "SharedAlbListenerArn"},
                ]
            }
        },
    }


def test_builders_create_shared_alb_fargate_service_stack_core() -> None:
    config = _shared_alb_config()

    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

    assert service == _jinja_service_to_dict(config)


def test_builders_create_minimal_service_stack_core() -> None:
    config = _config()

    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

    assert service == _jinja_service_to_dict(config)


def test_builders_add_ses_send_email_task_policy() -> None:
    config = _shared_alb_config()
    config.services[0].enable_ses_send_email = True

    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

    assert service == _jinja_service_to_dict(config)
    policies = service["Resources"]["TaskRole"]["Properties"]["Policies"]
    assert {
        "PolicyName": "SesSendEmail",
        "PolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ses:SendEmail",
                        "ses:SendRawEmail",
                        "ses:GetSendQuota",
                    ],
                    "Resource": "*",
                }
            ],
        },
    } in policies


def test_builders_add_configured_tag_plumbing() -> None:
    config = _config()
    config.tags = {"owner": "platform"}
    config.environment_overrides = {
        "dev": EnvironmentOverride(tags={"cost-center": "dev-sandbox"})
    }

    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    assert root["Parameters"]["ExtraTagCostCenter"] == {
        "Type": "String",
        "Default": "",
    }
    assert root["Parameters"]["ExtraTagOwner"] == {
        "Type": "String",
        "Default": "platform",
    }
    assert root["Conditions"]["HasExtraTagCostCenter"] == {
        "Fn::Not": [
            {"Fn::Equals": [{"Ref": "ExtraTagCostCenter"}, ""]}
        ]
    }
    owner_tag = {
        "Fn::If": [
            "HasExtraTagOwner",
            {"Key": "owner", "Value": {"Ref": "ExtraTagOwner"}},
            {"Ref": "AWS::NoValue"},
        ]
    }
    assert owner_tag in root["Resources"]["EcsCluster"]["Properties"]["Tags"]
    assert root["Resources"]["ServiceWeb"]["Properties"]["Parameters"][
        "ExtraTagCostCenter"
    ] == {"Ref": "ExtraTagCostCenter"}
    assert owner_tag in root["Resources"]["CustomOverrides"]["Properties"]["Tags"]


def test_builders_add_cluster_routing_priority_parameters() -> None:
    config = _config()
    config.alb = AlbConfig(
        domain="app.example.com",
        default_target_service="web",
        default_listener_priority=100,
        path_rules=[
            AlbPathRule(
                name="api-v2",
                path_pattern="/api/v2/*",
                target_service="web",
                priority=110,
            )
        ],
    )

    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    assert root["Parameters"]["DefaultListenerPriority"] == {"Type": "Number"}
    assert root["Parameters"]["PathRulePriorityApiV2"] == {"Type": "Number"}
    service_parameters = root["Resources"]["ServiceWeb"]["Properties"][
        "Parameters"
    ]
    assert service_parameters["DefaultListenerPriority"] == {
        "Ref": "DefaultListenerPriority"
    }
    assert service_parameters["PathRulePriorityApiV2"] == {
        "Ref": "PathRulePriorityApiV2"
    }


def test_builders_add_dedicated_alb_certificate_and_dns_resources() -> None:
    config = _dedicated_alb_config()
    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )
    jinja_root = _jinja_root_to_dict(config)

    for logical_id in (
        "DedicatedAlb",
        "DedicatedAlbSecurityGroup",
        "DedicatedAlbHttpListener",
        "DedicatedAlbHttpsListener",
        "DnsRecord",
    ):
        expected = jinja_root["Resources"][logical_id]
        if logical_id in {
            "DedicatedAlbHttpListener",
            "DedicatedAlbHttpsListener",
        }:
            expected["Properties"].pop("Tags")
        assert root["Resources"][logical_id] == expected
    assert root["Resources"]["ServiceWeb"] == jinja_root["Resources"][
        "ServiceWeb"
    ]
    assert root["Outputs"]["AlbListenerArn"] == jinja_root["Outputs"][
        "AlbListenerArn"
    ]


def test_builders_add_dedicated_alb_without_certificate_listener_variant() -> None:
    config = _dedicated_alb_config(certificate=False)
    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )
    jinja_root = _jinja_root_to_dict(config)

    assert root["Parameters"]["CertificateArn"]["Default"] == ""
    assert root["Conditions"]["UseDedicatedAlbNoCert"] == jinja_root[
        "Conditions"
    ]["UseDedicatedAlbNoCert"]
    expected = jinja_root["Resources"]["DedicatedAlbHttpListener"]
    expected["Properties"].pop("Tags")
    assert root["Resources"]["DedicatedAlbHttpListener"] == expected


def test_builders_add_feature_conditional_parameters_and_conditions() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", enable_service_discovery=True)],
        rds=RdsConfig(database_name="demo", instance_type="db.t4g.small"),
        secrets=[
            SecretConfig(name="API_TOKEN", source=SecretSource.ENV),
            SecretConfig(
                name="EXISTING_KEY",
                source=SecretSource.EXISTING,
                existing_secret_name="shared/key",
            ),
            SecretConfig(name="GENERATED_KEY", source=SecretSource.GENERATE),
            SecretConfig(
                name="DATABASE_PASSWORD",
                source=SecretSource.RDS,
                existing_secret_name="password",
            ),
        ],
    )

    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    assert root["Parameters"]["RdsSnapshotIdentifier"] == {
        "Type": "String",
        "Default": "",
    }
    assert root["Parameters"]["RdsSourceSecretArn"] == {
        "Type": "String",
        "Default": "",
    }
    assert root["Parameters"]["RdsInstanceType"] == {
        "Type": "String",
        "Default": "db.t4g.small",
    }
    assert root["Conditions"]["HasRdsSnapshot"] == {
        "Fn::Not": [
            {"Fn::Equals": [{"Ref": "RdsSnapshotIdentifier"}, ""]}
        ]
    }
    assert root["Parameters"]["ExistingCloudMapNamespaceId"] == {
        "Type": "String",
        "Default": "",
    }
    assert root["Conditions"]["HasExistingCloudMapNamespace"] == {
        "Fn::Not": [
            {
                "Fn::Equals": [
                    {"Ref": "ExistingCloudMapNamespaceId"},
                    "",
                ]
            }
        ]
    }
    assert root["Conditions"]["CreateServiceNamespace"] == {
        "Fn::Equals": [{"Ref": "ExistingCloudMapNamespaceId"}, ""]
    }
    assert root["Parameters"]["EnvSecretArnAPITOKEN"] == {"Type": "String"}
    assert root["Parameters"]["EnvSecretArnEXISTINGKEY"] == {"Type": "String"}
    assert "EnvSecretArnGENERATEDKEY" not in root["Parameters"]
    assert "EnvSecretArnDATABASEPASSWORD" not in root["Parameters"]


def test_builder_root_template_passes_cfn_lint(tmp_path: Path) -> None:
    root = build_project_templates(_dedicated_alb_config())[
        "templates/generated/root.yaml"
    ]

    assert_template_passes_cfn_lint(root, tmp_path / "root.yaml")


def test_builder_service_template_passes_cfn_lint(tmp_path: Path) -> None:
    service = build_project_templates(_shared_alb_config())[
        "templates/generated/services/web.yaml"
    ]

    assert_template_passes_cfn_lint(service, tmp_path / "web.yaml")
