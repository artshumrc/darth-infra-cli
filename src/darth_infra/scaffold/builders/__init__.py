"""Structural CloudFormation template builders."""

from __future__ import annotations

from typing import TypeAlias

from troposphere import (
    And,
    Condition,
    Equals,
    GetAtt,
    If,
    Join,
    Not,
    Output,
    Parameter,
    Ref,
    Sub,
    Tag,
    Tags,
    Template,
)
from troposphere import cloudformation, ecr, ecs

from ...config.models import ProjectConfig
from ..context import RenderContext, derive_render_context

ProjectTemplates: TypeAlias = dict[str, Template]


def _resource_tags(context: RenderContext) -> Tags:
    return Tags(
        Tag("Project", Ref("ProjectName")),
        Tag("Environment", Ref("EnvironmentName")),
        *(
            If(
                tag.condition_name,
                {"Key": tag.key, "Value": Ref(tag.parameter_name)},
                Ref("AWS::NoValue"),
            )
            for tag in context.tag_parameters
        ),
    )


def build_project_templates(config: ProjectConfig) -> ProjectTemplates:
    """Build generated project templates without performing I/O."""
    context = derive_render_context(config)
    root = Template(
        Description=f"darth-infra root stack for {context.project_name}"
    )
    root.set_version("2010-09-09")

    root.add_parameter(
        Parameter("ProjectName", Type="String", Default=context.project_name)
    )
    root.add_parameter(Parameter("EnvironmentName", Type="String"))
    root.add_parameter(Parameter("VpcId", Type="AWS::EC2::VPC::Id"))
    root.add_parameter(Parameter("VpcCidr", Type="String"))
    root.add_parameter(Parameter("PrivateSubnetIds", Type="CommaDelimitedList"))
    root.add_parameter(Parameter("PublicSubnetIds", Type="CommaDelimitedList"))
    root.add_parameter(
        Parameter(
            "AlbMode",
            Type="String",
            AllowedValues=["shared", "dedicated"],
            Default=context.alb.mode.value,
        )
    )
    for name in (
        "SharedAlbListenerArn",
        "SharedAlbSecurityGroupId",
        "SharedAlbDnsName",
        "SharedAlbCanonicalHostedZoneId",
        "HostedZoneId",
    ):
        root.add_parameter(Parameter(name, Type="String", Default=""))
    root.add_parameter(
        Parameter(
            "CertificateArn",
            Type="String",
            Default=context.alb.certificate_arn or "",
        )
    )
    root.add_parameter(
        Parameter(
            "ClusterDomain", Type="String", Default=context.alb.domain or ""
        )
    )
    if context.has_cluster_routing:
        root.add_parameter(Parameter("DefaultListenerPriority", Type="Number"))
        for rule in context.alb_path_rules_ctx:
            root.add_parameter(
                Parameter(rule.priority_param_name, Type="Number")
            )
    for tag in context.tag_parameters:
        root.add_parameter(
            Parameter(
                tag.parameter_name, Type="String", Default=tag.default_value
            )
        )
    if context.rds is not None:
        root.add_parameter(
            Parameter("RdsSnapshotIdentifier", Type="String", Default="")
        )
        root.add_parameter(
            Parameter("RdsSourceSecretArn", Type="String", Default="")
        )
        root.add_parameter(
            Parameter(
                "RdsInstanceType",
                Type="String",
                Default=context.rds.instance_type,
            )
        )
    if context.has_service_discovery:
        root.add_parameter(
            Parameter(
                "ExistingCloudMapNamespaceId", Type="String", Default=""
            )
        )
    for secret in context.secrets:
        if secret.source.value not in {"generate", "rds"}:
            root.add_parameter(
                Parameter(secret.external_parameter_name, Type="String")
            )

    root.add_condition("IsProd", Equals(Ref("EnvironmentName"), "prod"))
    root.add_condition(
        "UseDedicatedAlb", Equals(Ref("AlbMode"), "dedicated")
    )
    root.add_condition(
        "HasCertificate", Not(Equals(Ref("CertificateArn"), ""))
    )
    root.add_condition("HasHostedZone", Not(Equals(Ref("HostedZoneId"), "")))
    root.add_condition(
        "UseDedicatedAlbWithCert",
        And(Condition("UseDedicatedAlb"), Condition("HasCertificate")),
    )
    root.add_condition(
        "UseDedicatedAlbNoCert",
        And(Condition("UseDedicatedAlb"), Not(Condition("HasCertificate"))),
    )
    for tag in context.tag_parameters:
        root.add_condition(
            tag.condition_name, Not(Equals(Ref(tag.parameter_name), ""))
        )
    if context.has_rds:
        root.add_condition(
            "HasRdsSnapshot",
            Not(Equals(Ref("RdsSnapshotIdentifier"), "")),
        )
    if context.has_service_discovery:
        root.add_condition(
            "HasExistingCloudMapNamespace",
            Not(Equals(Ref("ExistingCloudMapNamespaceId"), "")),
        )
        root.add_condition(
            "CreateServiceNamespace",
            Equals(Ref("ExistingCloudMapNamespaceId"), ""),
        )

    cluster = root.add_resource(
        ecs.Cluster(
            "EcsCluster",
            ClusterName=Sub("${ProjectName}-${EnvironmentName}"),
            ClusterSettings=[
                ecs.ClusterSetting(Name="containerInsights", Value="enabled")
            ],
            Tags=_resource_tags(context),
        )
    )

    for service in context.services_ctx:
        repository = None
        if not service.svc.image:
            repository = root.add_resource(
                ecr.Repository(
                    f"EcrRepo{service.name_pascal}",
                    RepositoryName=Sub(
                        f"${{ProjectName}}/${{EnvironmentName}}/{service.name}"
                    ),
                    EmptyOnDelete=True,
                    Tags=_resource_tags(context),
                )
            )

        service_parameters = {
            "ProjectName": Ref("ProjectName"),
            "EnvironmentName": Ref("EnvironmentName"),
            "VpcId": Ref("VpcId"),
            "VpcCidr": Ref("VpcCidr"),
            "PrivateSubnetIds": Join(",", Ref("PrivateSubnetIds")),
            "ClusterName": Ref(cluster),
            "ClusterArn": GetAtt(cluster, "Arn"),
            "ClusterDomain": Ref("ClusterDomain"),
        }
        service_parameters.update(
            {
                tag.parameter_name: Ref(tag.parameter_name)
                for tag in context.tag_parameters
            }
        )
        if service.is_default_listener_target:
            parameter_name = service.default_listener_priority_param_name
            service_parameters[parameter_name] = Ref(parameter_name)
        service_parameters.update(
            {
                rule.priority_param_name: Ref(rule.priority_param_name)
                for rule in service.service_path_rules
            }
        )
        service_stack = cloudformation.Stack(
            f"Service{service.name_pascal}",
            TemplateURL=f"services/{service.name}.yaml",
            Parameters=service_parameters,
            Tags=_resource_tags(context),
        )
        if repository is not None:
            service_stack.DependsOn = repository.title
        root.add_resource(service_stack)

    root.add_resource(
        cloudformation.Stack(
            "CustomOverrides",
            TemplateURL="../custom/overrides.yaml",
            Tags=_resource_tags(context),
        )
    )
    root.add_output(Output("ClusterName", Value=Ref(cluster)))
    root.add_output(Output("StackEnvironment", Value=Ref("EnvironmentName")))

    return {"templates/generated/root.yaml": root}


__all__ = ["ProjectTemplates", "build_project_templates"]
