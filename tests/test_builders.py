from pathlib import Path

from darth_infra.config.models import (
    AlbConfig,
    AlbMode,
    AlbPathRule,
    EbsVolumeConfig,
    EnvironmentOverride,
    LaunchType,
    ProjectConfig,
    RdsConfig,
    S3BucketConfig,
    S3BucketConnection,
    S3BucketMode,
    SecretConfig,
    SecretSource,
    ServiceDiscoveryConfig,
    ServiceConfig,
)
from darth_infra.scaffold.builders import build_project_templates

from builders_expected import (
    DEDICATED_ALB_NOCERT,
    DEDICATED_ALB_ROOT,
    MINIMAL_SERVICE,
    RDS_ROOT_RESOURCES,
    S3_ROOT_BUCKET_MEDIAFILES,
    S3_ROOT_SERVICEWEB,
    S3_SERVICE,
    SERVICE_DISCOVERY_ROOT_NAMESPACE,
    SERVICE_DISCOVERY_ROOT_SERVICEWEB,
    SERVICE_DISCOVERY_SERVICE,
    SHARED_ALB_SERVICE,
)
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


def _rds_secrets_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="web",
                secrets=[
                    "APP_SECRET",
                    "EXISTING_TOKEN",
                    "ENV_TOKEN",
                    "DATABASE_HOST",
                    "DATABASE_PORT",
                    "DATABASE_DB",
                    "DATABASE_USER",
                    "DATABASE_PASSWORD",
                ],
            )
        ],
        secrets=[
            SecretConfig(name="APP_SECRET", source=SecretSource.GENERATE),
            SecretConfig(
                name="EXISTING_TOKEN",
                source=SecretSource.EXISTING,
                existing_secret_name="shared/existing-token",
            ),
            SecretConfig(name="ENV_TOKEN", source=SecretSource.ENV),
            SecretConfig(
                name="DATABASE_HOST",
                source=SecretSource.RDS,
                existing_secret_name="host",
            ),
            SecretConfig(
                name="DATABASE_PORT",
                source=SecretSource.RDS,
                existing_secret_name="port",
            ),
            SecretConfig(
                name="DATABASE_DB",
                source=SecretSource.RDS,
                existing_secret_name="dbname",
            ),
            SecretConfig(
                name="DATABASE_USER",
                source=SecretSource.RDS,
                existing_secret_name="username",
            ),
            SecretConfig(
                name="DATABASE_PASSWORD",
                source=SecretSource.RDS,
                existing_secret_name="password",
            ),
        ],
        rds=RdsConfig(
            database_name="demo_db",
            instance_type="db.t4g.small",
            allocated_storage_gb=30,
            engine_version="16",
            backup_retention_days=14,
            expose_to=["web"],
        ),
    )


def _service_discovery_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="web", port=8000, enable_service_discovery=True
            )
        ],
        service_discovery=ServiceDiscoveryConfig(
            namespace_template="{project}-{env}.local"
        ),
        service_discovery_configured=True,
    )


def _s3_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", port=8000)],
        s3_buckets=[
            S3BucketConfig(
                name="media-files",
                cors=True,
                connections=[
                    S3BucketConnection(
                        service="web", env_key="MEDIA_BUCKET"
                    )
                ],
            ),
            S3BucketConfig(
                name="shared-assets",
                mode=S3BucketMode.EXISTING,
                existing_bucket_name="company-shared-assets",
                connections=[
                    S3BucketConnection(
                        service="web",
                        env_key="SHARED_ASSETS_BUCKET",
                        read_only=True,
                    )
                ],
            ),
        ],
    )


def _ec2_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="worker",
                port=None,
                launch_type=LaunchType.EC2,
                ec2_instance_type="t4g.small",
                cpu=512,
                memory_mib=1024,
                desired_count=2,
                user_data_script_content=(
                    "echo '${literal}' > /var/tmp/user-data-value"
                ),
                ebs_volumes=[
                    EbsVolumeConfig(
                        name="worker-data",
                        size_gb=40,
                        mount_path="/data",
                        device_name="/dev/xvdf",
                    )
                ],
            )
        ],
    )


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

    assert service == SHARED_ALB_SERVICE


def test_builders_create_minimal_service_stack_core() -> None:
    config = _config()

    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

    assert service == MINIMAL_SERVICE


def test_builders_add_ses_send_email_task_policy() -> None:
    config = _shared_alb_config()
    config.services[0].enable_ses_send_email = True

    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

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

    for logical_id in (
        "DedicatedAlb",
        "DedicatedAlbSecurityGroup",
        "DedicatedAlbHttpListener",
        "DedicatedAlbHttpsListener",
        "DnsRecord",
        "ServiceWeb",
    ):
        assert (
            root["Resources"][logical_id]
            == DEDICATED_ALB_ROOT["Resources"][logical_id]
        )
    assert root["Outputs"]["AlbListenerArn"] == DEDICATED_ALB_ROOT["Outputs"][
        "AlbListenerArn"
    ]


def test_builders_add_dedicated_alb_without_certificate_listener_variant() -> None:
    config = _dedicated_alb_config(certificate=False)
    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    assert root["Parameters"]["CertificateArn"]["Default"] == ""
    assert root["Conditions"]["UseDedicatedAlbNoCert"] == DEDICATED_ALB_NOCERT[
        "Conditions"
    ]["UseDedicatedAlbNoCert"]
    assert (
        root["Resources"]["DedicatedAlbHttpListener"]
        == DEDICATED_ALB_NOCERT["DedicatedAlbHttpListener"]
    )


def test_builders_add_rds_and_secret_root_resources() -> None:
    config = _rds_secrets_config()
    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    for logical_id in (
        "SecretAPPSECRET",
        "RdsCredentialsSecret",
        "RdsSecurityGroup",
        "RdsSubnetGroup",
        "Database",
        "RdsSecretAttachment",
        "ServiceWeb",
        "RdsIngressFromWeb",
    ):
        assert root["Resources"][logical_id] == RDS_ROOT_RESOURCES[logical_id]


def test_builders_wire_all_secret_sources_and_rds_environment_keys() -> None:
    config = _rds_secrets_config()
    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/web.yaml"
        ]
    )

    container = service["Resources"]["TaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]
    assert container["Secrets"] == [
        {"Name": "APP_SECRET", "ValueFrom": {"Ref": "SecretArnAPPSECRET"}},
        {
            "Name": "EXISTING_TOKEN",
            "ValueFrom": {"Ref": "SecretArnEXISTINGTOKEN"},
        },
        {"Name": "ENV_TOKEN", "ValueFrom": {"Ref": "SecretArnENVTOKEN"}},
        {
            "Name": "DATABASE_HOST",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:host::"},
        },
        {
            "Name": "DATABASE_PORT",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:port::"},
        },
        {
            "Name": "DATABASE_DB",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:dbname::"},
        },
        {
            "Name": "DATABASE_USER",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:username::"},
        },
        {
            "Name": "DATABASE_PASSWORD",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:password::"},
        },
        {
            "Name": "POSTGRES_DB",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:dbname::"},
        },
        {
            "Name": "POSTGRES_USER",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:username::"},
        },
        {
            "Name": "POSTGRES_PASSWORD",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:password::"},
        },
        {
            "Name": "POSTGRES_HOST",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:host::"},
        },
        {
            "Name": "POSTGRES_PORT",
            "ValueFrom": {"Fn::Sub": "${RdsSecretArn}:port::"},
        },
    ]


def test_builders_add_service_discovery_namespace_and_service_registry() -> None:
    config = _service_discovery_config()
    templates = build_project_templates(config)
    root = template_to_dict(templates["templates/generated/root.yaml"])
    service = template_to_dict(
        templates["templates/generated/services/web.yaml"]
    )

    assert root["Resources"]["ServiceNamespace"] == SERVICE_DISCOVERY_ROOT_NAMESPACE
    assert root["Resources"]["ServiceWeb"] == SERVICE_DISCOVERY_ROOT_SERVICEWEB
    assert service == SERVICE_DISCOVERY_SERVICE


def test_builders_add_managed_and_existing_s3_bucket_connections() -> None:
    config = _s3_config()
    templates = build_project_templates(config)
    root = template_to_dict(templates["templates/generated/root.yaml"])
    service = template_to_dict(
        templates["templates/generated/services/web.yaml"]
    )

    assert root["Resources"]["Bucketmediafiles"] == S3_ROOT_BUCKET_MEDIAFILES
    assert "Bucketsharedassets" not in root["Resources"]
    assert root["Resources"]["ServiceWeb"] == S3_ROOT_SERVICEWEB
    assert service == S3_SERVICE


def test_builders_add_ec2_launch_type_resources_and_capacity_wiring() -> None:
    config = _ec2_config()
    service = template_to_dict(
        build_project_templates(config)[
            "templates/generated/services/worker.yaml"
        ]
    )

    resources = service["Resources"]
    assert {
        "Ec2InstanceRole",
        "Ec2InstanceProfile",
        "LaunchTemplate",
        "AutoScalingGroup",
    } <= resources.keys()
    user_data = resources["LaunchTemplate"]["Properties"][
        "LaunchTemplateData"
    ]["UserData"]["Fn::Base64"]["Fn::Sub"]
    assert "echo '\\${!literal}' > /var/tmp/user-data-value" in user_data
    assert resources["EcsService"]["Properties"]["LaunchType"] == "EC2"


def test_builders_do_not_add_ec2_resources_to_fargate_service() -> None:
    service = template_to_dict(
        build_project_templates(_config())[
            "templates/generated/services/web.yaml"
        ]
    )

    assert {
        "Ec2InstanceRole",
        "Ec2InstanceProfile",
        "LaunchTemplate",
        "AutoScalingGroup",
    }.isdisjoint(service["Resources"])


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


def test_builders_default_service_discovery_namespace_to_legacy_local() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web", enable_service_discovery=True)],
    )

    root = template_to_dict(
        build_project_templates(config)["templates/generated/root.yaml"]
    )

    assert root["Resources"]["ServiceNamespace"]["Properties"]["Name"] == {
        "Fn::Sub": "local"
    }


def test_builders_propagate_cleanup_tags_to_ec2_capacity_resources() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[
            ServiceConfig(
                name="worker",
                launch_type=LaunchType.EC2,
                ec2_instance_type="t3.medium",
            )
        ],
        tags={"ephemeral-cleanup-id": "demo-pr-123"},
    )

    templates = build_project_templates(config)
    service = template_to_dict(
        templates["templates/generated/services/worker.yaml"]
    )

    assert service["Parameters"]["ExtraTagEphemeralCleanupId"] == {
        "Type": "String",
        "Default": "",
    }
    assert service["Conditions"]["HasExtraTagEphemeralCleanupId"] == {
        "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEphemeralCleanupId"}, ""]}]
    }
    asg_tags = service["Resources"]["AutoScalingGroup"]["Properties"]["Tags"]
    assert {
        "Fn::If": [
            "HasExtraTagEphemeralCleanupId",
            {
                "Key": "ephemeral-cleanup-id",
                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                "PropagateAtLaunch": True,
            },
            {"Ref": "AWS::NoValue"},
        ]
    } in asg_tags


def test_builder_root_template_passes_cfn_lint(tmp_path: Path) -> None:
    root = build_project_templates(_dedicated_alb_config())[
        "templates/generated/root.yaml"
    ]

    assert_template_passes_cfn_lint(root, tmp_path / "root.yaml")


def test_builder_service_template_passes_cfn_lint(tmp_path: Path) -> None:
    service = build_project_templates(_rds_secrets_config())[
        "templates/generated/services/web.yaml"
    ]

    assert_template_passes_cfn_lint(service, tmp_path / "web.yaml")


def test_builder_s3_service_template_passes_cfn_lint(tmp_path: Path) -> None:
    service = build_project_templates(_s3_config())[
        "templates/generated/services/web.yaml"
    ]

    assert_template_passes_cfn_lint(service, tmp_path / "web-s3.yaml")


def test_builder_ec2_service_template_passes_cfn_lint(tmp_path: Path) -> None:
    service = build_project_templates(_ec2_config())[
        "templates/generated/services/worker.yaml"
    ]

    assert_template_passes_cfn_lint(service, tmp_path / "worker-ec2.yaml")


def test_builders_dedicated_alb_listeners_carry_project_tags() -> None:
    # Regression: troposphere 4.10.2 omits Tags from Listener.props, which
    # silently dropped project/environment tags from both dedicated-ALB
    # listeners. CloudFormation does accept Tags there.
    root = template_to_dict(
        build_project_templates(_dedicated_alb_config())[
            "templates/generated/root.yaml"
        ]
    )

    for logical_id in ("DedicatedAlbHttpListener", "DedicatedAlbHttpsListener"):
        assert (
            root["Resources"][logical_id]["Properties"]["Tags"] == _expected_tags()
        ), f"{logical_id} lost its resource tags"
