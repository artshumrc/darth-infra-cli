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
    Split,
    Sub,
    Tag,
    Tags,
    Template,
)
from troposphere import (
    cloudformation,
    ec2,
    ecr,
    ecs,
    elasticloadbalancingv2,
    iam,
    logs,
)

from ...config.models import ProjectConfig
from ..context import RenderContext, ServiceRenderContext, derive_render_context

ProjectTemplates: TypeAlias = dict[str, Template]


class _LegacySecurityGroupEgress(ec2.SecurityGroupEgress):
    def validate(self) -> None:
        # Jinja emitted numeric -1, which troposphere's string-only validator rejects.
        return


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


def _service_tags(
    context: RenderContext, service: ServiceRenderContext
) -> Tags:
    return Tags(
        Tag("Project", Ref("ProjectName")),
        Tag("Environment", Ref("EnvironmentName")),
        Tag("Service", service.name),
        *(
            If(
                tag.condition_name,
                {"Key": tag.key, "Value": Ref(tag.parameter_name)},
                Ref("AWS::NoValue"),
            )
            for tag in context.tag_parameters
        ),
    )


def _task_assume_role_policy() -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


def _build_service_template(
    context: RenderContext, service: ServiceRenderContext
) -> Template:
    template = Template(
        Description=(
            f"ECS service stack for {context.project_name}/{service.name}"
        )
    )
    template.set_version("2010-09-09")

    for name, parameter_type in (
        ("ProjectName", "String"),
        ("EnvironmentName", "String"),
        ("VpcId", "AWS::EC2::VPC::Id"),
        ("VpcCidr", "String"),
        ("PrivateSubnetIds", "String"),
        ("ClusterName", "String"),
        ("ClusterArn", "String"),
        ("ClusterDomain", "String"),
        ("AlbListenerArn", "String"),
        ("AlbSecurityGroupId", "String"),
    ):
        template.add_parameter(Parameter(name, Type=parameter_type))
    if service.is_default_listener_target:
        template.add_parameter(
            Parameter(service.default_listener_priority_param_name, Type="Number")
        )
    for rule in service.service_path_rules:
        template.add_parameter(Parameter(rule.priority_param_name, Type="Number"))
    for tag in context.tag_parameters:
        template.add_parameter(
            Parameter(tag.parameter_name, Type="String", Default="")
        )
        template.add_condition(
            tag.condition_name, Not(Equals(Ref(tag.parameter_name), ""))
        )

    tags = _service_tags(context, service)
    log_group = template.add_resource(
        logs.LogGroup(
            "LogGroup",
            LogGroupName=Sub(
                f"/ecs/${{ProjectName}}-${{EnvironmentName}}-{service.name}"
            ),
            RetentionInDays=30,
            Tags=tags,
        )
    )
    task_security_group = template.add_resource(
        ec2.SecurityGroup(
            "TaskSecurityGroup",
            GroupDescription=Sub(
                f"${{ProjectName}}-${{EnvironmentName}}-{service.name} ecs tasks"
            ),
            VpcId=Ref("VpcId"),
            Tags=tags,
        )
    )
    if service.has_alb_target:
        template.add_resource(
            ec2.SecurityGroupIngress(
                "TaskSgIngressFromAlb",
                GroupId=Ref(task_security_group),
                IpProtocol="tcp",
                FromPort=service.svc.port,
                ToPort=service.svc.port,
                SourceSecurityGroupId=Ref("AlbSecurityGroupId"),
            )
        )
    else:
        task_egress = _LegacySecurityGroupEgress(
            "TaskSgIngressFromAlb",
            GroupId=Ref(task_security_group),
            IpProtocol="-1",
            CidrIp="0.0.0.0/0",
        )
        # Preserve the Jinja template's numeric representation for no-op deploys.
        task_egress.properties["IpProtocol"] = -1
        template.add_resource(task_egress)
    if service.svc.port is not None and service.svc.enable_service_discovery:
        template.add_resource(
            ec2.SecurityGroupIngress(
                "TaskSgIngressFromServiceDiscovery",
                GroupId=Ref(task_security_group),
                IpProtocol="tcp",
                FromPort=service.svc.port,
                ToPort=service.svc.port,
                CidrIp=Ref("VpcCidr"),
            )
        )

    task_execution_role = template.add_resource(
        iam.Role(
            "TaskExecutionRole",
            AssumeRolePolicyDocument=_task_assume_role_policy(),
            ManagedPolicyArns=[
                "arn:aws:iam::aws:policy/service-role/"
                "AmazonECSTaskExecutionRolePolicy"
            ],
            Policies=[],
            Tags=tags,
        )
    )
    task_policies = []
    if service.svc.enable_exec:
        task_policies.append(
            iam.Policy(
                PolicyName="EcsExecSsm",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "ssmmessages:CreateControlChannel",
                                "ssmmessages:CreateDataChannel",
                                "ssmmessages:OpenControlChannel",
                                "ssmmessages:OpenDataChannel",
                            ],
                            "Resource": "*",
                        }
                    ],
                },
            )
        )
    if service.svc.enable_ses_send_email:
        task_policies.append(
            iam.Policy(
                PolicyName="SesSendEmail",
                PolicyDocument={
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
            )
        )
    task_role = template.add_resource(
        iam.Role(
            "TaskRole",
            AssumeRolePolicyDocument=_task_assume_role_policy(),
            Policies=task_policies,
            Tags=tags,
        )
    )

    environment = [
        ecs.Environment(Name="ENVIRONMENT", Value=Ref("EnvironmentName")),
        ecs.Environment(Name="SERVICE_NAME", Value=service.name),
        *(
            ecs.Environment(Name=name, Value=value)
            for name, value in service.svc.environment_variables.items()
        ),
    ]
    container = ecs.ContainerDefinition(
        Name=service.name,
        Image=(
            service.svc.image
            or Sub(
                "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/"
                f"${{ProjectName}}/${{EnvironmentName}}/{service.name}:latest"
            )
        ),
        Essential=True,
        LogConfiguration=ecs.LogConfiguration(
            LogDriver="awslogs",
            Options={
                "awslogs-group": Ref(log_group),
                "awslogs-region": Ref("AWS::Region"),
                "awslogs-stream-prefix": service.name,
            },
        ),
        Environment=environment,
    )
    if service.svc.command:
        container.Command = ["sh", "-c", service.svc.command]
    if service.svc.port is not None:
        container.PortMappings = [
            ecs.PortMapping(ContainerPort=service.svc.port, Protocol="tcp")
        ]
    task_definition = template.add_resource(
        ecs.TaskDefinition(
            "TaskDefinition",
            Family=Sub(
                f"${{ProjectName}}-${{EnvironmentName}}-{service.name}"
            ),
            NetworkMode="awsvpc",
            RequiresCompatibilities=["FARGATE"],
            Cpu=str(service.svc.cpu),
            Memory=str(service.svc.memory_mib),
            ExecutionRoleArn=GetAtt(task_execution_role, "Arn"),
            TaskRoleArn=GetAtt(task_role, "Arn"),
            Tags=tags,
            ContainerDefinitions=[container],
        )
    )

    target_group = None
    if service.has_alb_target:
        target_group = template.add_resource(
            elasticloadbalancingv2.TargetGroup(
                "TargetGroup",
                Port=service.svc.port,
                Protocol="HTTP",
                TargetType="ip",
                VpcId=Ref("VpcId"),
                HealthCheckPath=service.svc.health_check_path,
                HealthCheckTimeoutSeconds=(
                    service.svc.health_check_timeout_seconds
                ),
                HealthCheckIntervalSeconds=(
                    service.svc.health_check_interval_seconds
                ),
                HealthyThresholdCount=service.svc.healthy_threshold_count,
                UnhealthyThresholdCount=service.svc.unhealthy_threshold_count,
                Matcher=elasticloadbalancingv2.Matcher(
                    HttpCode=service.svc.health_check_http_codes
                ),
                Tags=tags,
            )
        )

    listener_dependencies = []
    host_header_condition = elasticloadbalancingv2.Condition(
        Field="host-header",
        HostHeaderConfig=elasticloadbalancingv2.HostHeaderConfig(
            Values=[
                Ref(host.ref_name) if host.is_ref else host.value
                for host in service.listener_hostnames
            ]
        ),
    )
    if target_group is not None and service.has_cluster_routing_rules:
        if service.is_default_listener_target:
            default_listener_rule = template.add_resource(
                elasticloadbalancingv2.ListenerRule(
                    "DefaultHostHeaderRule",
                    Actions=[
                        elasticloadbalancingv2.ListenerRuleAction(
                            Type="forward", TargetGroupArn=Ref(target_group)
                        )
                    ],
                    Conditions=[host_header_condition],
                    ListenerArn=Ref("AlbListenerArn"),
                    Priority=Ref(
                        service.default_listener_priority_param_name
                    ),
                )
            )
            listener_dependencies.append(default_listener_rule.title)
        for rule in service.service_path_rules:
            path_listener_rule = template.add_resource(
                elasticloadbalancingv2.ListenerRule(
                    f"PathRule{rule.name_pascal}",
                    Actions=[
                        elasticloadbalancingv2.ListenerRuleAction(
                            Type="forward", TargetGroupArn=Ref(target_group)
                        )
                    ],
                    Conditions=[
                        host_header_condition,
                        elasticloadbalancingv2.Condition(
                            Field="path-pattern",
                            PathPatternConfig=(
                                elasticloadbalancingv2.PathPatternConfig(
                                    Values=[rule.path_pattern]
                                )
                            ),
                        ),
                    ],
                    ListenerArn=Ref("AlbListenerArn"),
                    Priority=Ref(rule.priority_param_name),
                )
            )
            listener_dependencies.append(path_listener_rule.title)

    ecs_service = ecs.Service(
        "EcsService",
        DependsOn=[task_definition.title, *listener_dependencies],
        ServiceName=Sub(
            f"${{ProjectName}}-${{EnvironmentName}}-{service.name}"
        ),
        Cluster=Ref("ClusterArn"),
        DesiredCount=service.svc.desired_count,
        EnableExecuteCommand=service.svc.enable_exec,
        LaunchType="FARGATE",
        TaskDefinition=Ref(task_definition),
        PropagateTags="TASK_DEFINITION",
        Tags=tags,
        NetworkConfiguration=ecs.NetworkConfiguration(
            AwsvpcConfiguration=ecs.AwsvpcConfiguration(
                AssignPublicIp="DISABLED",
                SecurityGroups=[Ref(task_security_group)],
                Subnets=Split(",", Ref("PrivateSubnetIds")),
            )
        ),
    )
    if (
        target_group is not None
        and service.svc.health_check_grace_period_seconds is not None
    ):
        ecs_service.HealthCheckGracePeriodSeconds = (
            service.svc.health_check_grace_period_seconds
        )
    if target_group is not None:
        ecs_service.LoadBalancers = [
            ecs.LoadBalancer(
                ContainerName=service.name,
                ContainerPort=service.svc.port,
                TargetGroupArn=Ref(target_group),
            )
        ]
    template.add_resource(ecs_service)

    template.add_output(Output("ServiceName", Value=Ref(ecs_service)))
    template.add_output(
        Output("TaskSecurityGroupId", Value=Ref(task_security_group))
    )
    if target_group is not None:
        template.add_output(Output("TargetGroupArn", Value=Ref(target_group)))
    return template


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
            "AlbListenerArn": Ref("SharedAlbListenerArn"),
            "AlbSecurityGroupId": Ref("SharedAlbSecurityGroupId"),
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

    templates = {"templates/generated/root.yaml": root}
    for service in context.services_ctx:
        templates[f"templates/generated/services/{service.name}.yaml"] = (
            _build_service_template(context, service)
        )
    return templates


__all__ = ["ProjectTemplates", "build_project_templates"]
