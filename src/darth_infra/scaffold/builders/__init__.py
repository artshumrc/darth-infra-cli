"""Structural CloudFormation template builders."""

from __future__ import annotations

from typing import TypeAlias

from troposphere import (
    And,
    Base64,
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
    autoscaling,
    cloudformation,
    cloudfront,
    ec2,
    ecr,
    ecs,
    elasticloadbalancingv2,
    iam,
    logs,
    rds,
    route53,
    s3,
    secretsmanager,
    servicediscovery,
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


def _alb_cached_behavior_forwarded_values(
    behavior: object,
) -> cloudfront.ForwardedValues:
    if behavior.query_strings == "none":
        forwarded_values = cloudfront.ForwardedValues(QueryString=False)
    else:
        forwarded_values = cloudfront.ForwardedValues(QueryString=True)
        if (
            behavior.query_strings == "allowlist"
            and behavior.query_string_allowlist
        ):
            forwarded_values.QueryStringCacheKeys = list(
                behavior.query_string_allowlist
            )
    if behavior.cookies == "all":
        forwarded_values.Cookies = cloudfront.Cookies(Forward="all")
    elif behavior.cookies == "allowlist":
        forwarded_values.Cookies = cloudfront.Cookies(
            Forward="whitelist",
            WhitelistedNames=list(behavior.cookie_allowlist),
        )
    else:
        forwarded_values.Cookies = cloudfront.Cookies(Forward="none")
    headers = ["Host"]
    if behavior.forward_authorization_header:
        headers.append("Authorization")
    forwarded_values.Headers = headers
    return forwarded_values


def _build_alb_cloudfront(context: RenderContext) -> cloudfront.Distribution:
    alb_cloudfront = context.alb_cloudfront
    distribution_config = cloudfront.DistributionConfig(
        Enabled=True,
        PriceClass=alb_cloudfront.price_class,
        Origins=[
            cloudfront.Origin(
                DomainName=If(
                    "UseDedicatedAlb",
                    GetAtt("DedicatedAlb", "DNSName"),
                    Ref("SharedAlbDnsName"),
                ),
                Id="AlbOrigin",
                CustomOriginConfig=cloudfront.CustomOriginConfig(
                    HTTPPort=80,
                    HTTPSPort=443,
                    OriginProtocolPolicy=(
                        "https-only"
                        if alb_cloudfront.origin_https_only
                        else "http-only"
                    ),
                ),
            )
        ],
        DefaultCacheBehavior=cloudfront.DefaultCacheBehavior(
            TargetOriginId="AlbOrigin",
            ViewerProtocolPolicy="redirect-to-https",
            AllowedMethods=[
                "GET",
                "HEAD",
                "OPTIONS",
                "PUT",
                "PATCH",
                "POST",
                "DELETE",
            ],
            CachedMethods=["GET", "HEAD", "OPTIONS"],
            Compress=True,
            MinTTL=0,
            DefaultTTL=0,
            MaxTTL=0,
            ForwardedValues=cloudfront.ForwardedValues(
                QueryString=True,
                Cookies=cloudfront.Cookies(Forward="all"),
                Headers=["*"],
            ),
        ),
    )
    if alb_cloudfront.comment:
        distribution_config.Comment = alb_cloudfront.comment
    if alb_cloudfront.custom_domain:
        distribution_config.Aliases = [alb_cloudfront.custom_domain]
    if alb_cloudfront.certificate_arn:
        distribution_config.ViewerCertificate = cloudfront.ViewerCertificate(
            AcmCertificateArn=alb_cloudfront.certificate_arn,
            SslSupportMethod="sni-only",
            MinimumProtocolVersion="TLSv1.2_2021",
        )
    if alb_cloudfront.cached_behaviors:
        distribution_config.CacheBehaviors = [
            cloudfront.CacheBehavior(
                PathPattern=behavior.path_pattern,
                TargetOriginId="AlbOrigin",
                ViewerProtocolPolicy="redirect-to-https",
                AllowedMethods=[
                    "GET",
                    "HEAD",
                    "OPTIONS",
                    "PUT",
                    "PATCH",
                    "POST",
                    "DELETE",
                ],
                CachedMethods=["GET", "HEAD", "OPTIONS"],
                Compress=behavior.compress,
                MinTTL=behavior.min_ttl_seconds,
                DefaultTTL=behavior.default_ttl_seconds,
                MaxTTL=behavior.max_ttl_seconds,
                ForwardedValues=_alb_cached_behavior_forwarded_values(behavior),
            )
            for behavior in alb_cloudfront.cached_behaviors
        ]
    return cloudfront.Distribution(
        "AlbCloudFront",
        DistributionConfig=distribution_config,
        Tags=_resource_tags(context),
    )


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
    if service.has_rds:
        template.add_parameter(Parameter("RdsSecretArn", Type="String"))
    if service.svc.enable_service_discovery:
        template.add_parameter(Parameter("CloudMapNamespaceId", Type="String"))
    for secret in service.secret_params:
        if secret.requires_param:
            template.add_parameter(Parameter(secret.param_name, Type="String"))
    for s3_access in service.s3_vars:
        template.add_parameter(Parameter(s3_access.param_name, Type="String"))
        template.add_parameter(Parameter(s3_access.arn_param_name, Type="String"))
        if s3_access.fallback_param_name:
            template.add_parameter(
                Parameter(s3_access.fallback_param_name, Type="String")
            )
            template.add_parameter(
                Parameter(s3_access.fallback_arn_param_name, Type="String")
            )
    for s3_access in service.s3_vars:
        if s3_access.cf_param_name:
            template.add_parameter(
                Parameter(s3_access.cf_param_name, Type="String")
            )
    for cloudfront_access in service.cloudfront_vars:
        template.add_parameter(
            Parameter(cloudfront_access.param_name, Type="String")
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

    execution_policies = []
    if service.secret_params or service.has_rds:
        secret_resources = [
            Ref(secret.param_name)
            for secret in service.secret_params
            if secret.requires_param
        ]
        if service.has_rds:
            secret_resources.append(Ref("RdsSecretArn"))
        execution_policies.append(
            iam.Policy(
                PolicyName="ReadSecrets",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": secret_resources,
                        }
                    ],
                },
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
            Policies=execution_policies,
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
    if service.s3_vars:
        s3_statements = []
        for s3_access in service.s3_vars:
            s3_statements.append(
                {
                    "Effect": "Allow",
                    "Action": (
                        ["s3:GetObject", "s3:ListBucket"]
                        if s3_access.read_only
                        else [
                            "s3:GetObject",
                            "s3:PutObject",
                            "s3:DeleteObject",
                            "s3:ListBucket",
                        ]
                    ),
                    "Resource": [
                        Ref(s3_access.arn_param_name),
                        Join(
                            "",
                            [Ref(s3_access.arn_param_name), "/*"],
                        ),
                    ],
                }
            )
            if s3_access.fallback_arn_param_name:
                s3_statements.append(
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:ListBucket"],
                        "Resource": [
                            Ref(s3_access.fallback_arn_param_name),
                            Join(
                                "",
                                [
                                    Ref(s3_access.fallback_arn_param_name),
                                    "/*",
                                ],
                            ),
                        ],
                    }
                )
        task_policies.append(
            iam.Policy(
                PolicyName="S3Access",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": s3_statements,
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

    if service.launch_type == "ec2":
        instance_role = template.add_resource(
            iam.Role(
                "Ec2InstanceRole",
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                ManagedPolicyArns=[
                    "arn:aws:iam::aws:policy/service-role/"
                    "AmazonEC2ContainerServiceforEC2Role"
                ],
                Tags=tags,
            )
        )
        instance_profile = template.add_resource(
            iam.InstanceProfile(
                "Ec2InstanceProfile", Roles=[Ref(instance_role)]
            )
        )

        user_data_lines = [
            "#!/bin/bash",
            'echo "ECS_CLUSTER=${ProjectName}-${EnvironmentName}" '
            ">> /etc/ecs/ecs.config",
            'echo "ECS_ENABLE_TASK_IAM_ROLE=true" >> /etc/ecs/ecs.config',
        ]
        for volume in service.ebs_params:
            user_data_lines.extend(
                [
                    f"if ! blkid {volume.device_name}; then",
                    f"  mkfs.{volume.filesystem_type} {volume.device_name}",
                    "fi",
                    f"mkdir -p {volume.mount_path}",
                    (
                        f'echo "{volume.device_name} {volume.mount_path} '
                        f'{volume.filesystem_type} defaults,nofail 0 2" '
                        ">> /etc/fstab"
                    ),
                    f"mount {volume.mount_path}",
                ]
            )
        if service.user_data_script_content:
            user_data_lines.append(service.user_data_script_content)
        user_data = "\n".join(user_data_lines) + "\n"

        block_device_mappings = [
            ec2.LaunchTemplateBlockDeviceMapping(
                DeviceName=volume.device_name,
                Ebs=ec2.EBSBlockDevice(
                    VolumeType=volume.volume_type,
                    VolumeSize=volume.size_gb,
                    DeleteOnTermination=False,
                ),
            )
            for volume in service.ebs_params
        ]
        if not block_device_mappings:
            block_device_mappings.append(
                ec2.LaunchTemplateBlockDeviceMapping(
                    DeviceName="/dev/xvda",
                    Ebs=ec2.EBSBlockDevice(
                        VolumeType="gp3", VolumeSize=30
                    ),
                )
            )

        launch_template = template.add_resource(
            ec2.LaunchTemplate(
                "LaunchTemplate",
                TagSpecifications=[
                    ec2.TagSpecifications(
                        ResourceType="launch-template", Tags=tags
                    )
                ],
                LaunchTemplateData=ec2.LaunchTemplateData(
                    IamInstanceProfile=ec2.IamInstanceProfile(
                        Arn=GetAtt(instance_profile, "Arn")
                    ),
                    ImageId=(
                        "{{resolve:ssm:/aws/service/ecs/optimized-ami/"
                        "amazon-linux-2/arm64/recommended/image_id}}"
                        if service.architecture == "arm64"
                        else "{{resolve:ssm:/aws/service/ecs/optimized-ami/"
                        "amazon-linux-2/recommended/image_id}}"
                    ),
                    InstanceType=service.svc.ec2_instance_type or "t3.medium",
                    SecurityGroupIds=[Ref(task_security_group)],
                    UserData=Base64(Sub(user_data)),
                    BlockDeviceMappings=block_device_mappings,
                    TagSpecifications=[
                        ec2.TagSpecifications(
                            ResourceType=resource_type, Tags=tags
                        )
                        for resource_type in ("instance", "volume")
                    ],
                ),
            )
        )
        propagated_tags = [
            autoscaling.Tag(
                "Name",
                Sub(
                    f"${{ProjectName}}-${{EnvironmentName}}-{service.name}"
                ),
                True,
            ),
            autoscaling.Tag("Project", Ref("ProjectName"), True),
            autoscaling.Tag("Environment", Ref("EnvironmentName"), True),
            autoscaling.Tag("Service", service.name, True),
            *(
                If(
                    tag.condition_name,
                    {
                        "Key": tag.key,
                        "Value": Ref(tag.parameter_name),
                        "PropagateAtLaunch": True,
                    },
                    Ref("AWS::NoValue"),
                )
                for tag in context.tag_parameters
            ),
        ]
        template.add_resource(
            autoscaling.AutoScalingGroup(
                "AutoScalingGroup",
                VPCZoneIdentifier=Split(",", Ref("PrivateSubnetIds")),
                MinSize=str(service.svc.desired_count),
                MaxSize=str(max(service.svc.desired_count * 2, 2)),
                DesiredCapacity=str(service.svc.desired_count),
                LaunchTemplate=autoscaling.LaunchTemplateSpecification(
                    LaunchTemplateId=Ref(launch_template),
                    Version=GetAtt(launch_template, "LatestVersionNumber"),
                ),
                Tags=propagated_tags,
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
    if service.has_rds:
        environment.append(
            ecs.Environment(Name="DB_SECRET_ARN", Value=Ref("RdsSecretArn"))
        )
    for s3_access in service.s3_vars:
        environment.append(
            ecs.Environment(
                Name=s3_access.env_key, Value=Ref(s3_access.param_name)
            )
        )
        if s3_access.fallback_env_key and s3_access.fallback_param_name:
            environment.append(
                ecs.Environment(
                    Name=s3_access.fallback_env_key,
                    Value=Ref(s3_access.fallback_param_name),
                )
            )
        if s3_access.cloudfront_env_key and s3_access.cf_param_name:
            environment.append(
                ecs.Environment(
                    Name=s3_access.cloudfront_env_key,
                    Value=Ref(s3_access.cf_param_name),
                )
            )
    for cloudfront_access in service.cloudfront_vars:
        environment.append(
            ecs.Environment(
                Name=cloudfront_access.env_key,
                Value=Ref(cloudfront_access.param_name),
            )
        )
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
    if service.secret_params or service.has_rds:
        container.Secrets = [
            ecs.Secret(
                Name=secret.secret_name,
                ValueFrom=(
                    Sub(f"${{RdsSecretArn}}:{secret.rds_json_key}::")
                    if secret.source == "rds"
                    else Ref(secret.param_name)
                ),
            )
            for secret in service.secret_params
        ]
    if service.svc.command:
        container.Command = ["sh", "-c", service.svc.command]
    if service.launch_type == "ec2":
        container.Cpu = service.svc.cpu
        container.Memory = service.svc.memory_mib
        if service.ebs_params:
            container.MountPoints = [
                ecs.MountPoint(
                    ContainerPath=volume.mount_path,
                    SourceVolume=volume.name,
                    ReadOnly=False,
                )
                for volume in service.ebs_params
            ]
    if service.svc.port is not None:
        container.PortMappings = [
            ecs.PortMapping(ContainerPort=service.svc.port, Protocol="tcp")
        ]
    task_definition_properties: dict[str, object] = {
        "Family": Sub(
            f"${{ProjectName}}-${{EnvironmentName}}-{service.name}"
        ),
        "NetworkMode": "awsvpc",
        "RequiresCompatibilities": [
            "EC2" if service.launch_type == "ec2" else "FARGATE"
        ],
        "ExecutionRoleArn": GetAtt(task_execution_role, "Arn"),
        "TaskRoleArn": GetAtt(task_role, "Arn"),
        "Tags": tags,
        "ContainerDefinitions": [container],
    }
    if service.launch_type == "fargate":
        task_definition_properties.update(
            Cpu=str(service.svc.cpu), Memory=str(service.svc.memory_mib)
        )
    elif service.ebs_params:
        task_definition_properties["Volumes"] = [
            ecs.Volume(
                Name=volume.name,
                Host=ecs.Host(SourcePath=volume.mount_path),
            )
            for volume in service.ebs_params
        ]
    task_definition = template.add_resource(
        ecs.TaskDefinition("TaskDefinition", **task_definition_properties)
    )

    cloud_map_service = None
    if service.svc.enable_service_discovery:
        cloud_map_service = template.add_resource(
            servicediscovery.Service(
                "CloudMapService",
                Name=service.name,
                NamespaceId=Ref("CloudMapNamespaceId"),
                DnsConfig=servicediscovery.DnsConfig(
                    DnsRecords=[
                        servicediscovery.DnsRecord(Type="A", TTL=10)
                    ]
                ),
                Tags=tags,
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
        LaunchType="EC2" if service.launch_type == "ec2" else "FARGATE",
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
    if cloud_map_service is not None:
        ecs_service.ServiceRegistries = [
            ecs.ServiceRegistry(RegistryArn=GetAtt(cloud_map_service, "Arn"))
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

    for bucket in context.s3_buckets:
        if not bucket.provision_bucket:
            continue
        bucket_properties: dict[str, object] = {
            "BucketName": Sub(
                f"${{ProjectName}}-${{EnvironmentName}}-{bucket.name}"
            ),
            "Tags": _resource_tags(context),
        }
        if bucket.cors:
            bucket_properties["CorsConfiguration"] = s3.CorsConfiguration(
                CorsRules=[
                    s3.CorsRules(
                        AllowedHeaders=["*"],
                        AllowedMethods=["GET", "PUT", "POST", "DELETE", "HEAD"],
                        AllowedOrigins=["*"],
                    )
                ]
            )
        root.add_resource(
            s3.Bucket(bucket.bucket_logical_id, **bucket_properties)
        )

    for bucket in context.s3_buckets:
        if not (bucket.cloudfront and bucket.provision_bucket):
            continue
        origin_id = f"S3{bucket.logical_id_fragment}Origin"
        root.add_resource(
            cloudfront.OriginAccessControl(
                bucket.cloudfront_oac_logical_id,
                OriginAccessControlConfig=(
                    cloudfront.OriginAccessControlConfig(
                        Name=Sub(
                            "${ProjectName}-${EnvironmentName}-"
                            f"{bucket.name}-oac"
                        ),
                        OriginAccessControlOriginType="s3",
                        SigningBehavior="always",
                        SigningProtocol="sigv4",
                    )
                ),
            )
        )
        root.add_resource(
            cloudfront.Distribution(
                bucket.cloudfront_logical_id,
                DistributionConfig=cloudfront.DistributionConfig(
                    Enabled=True,
                    Origins=[
                        cloudfront.Origin(
                            DomainName=GetAtt(
                                bucket.bucket_logical_id, "RegionalDomainName"
                            ),
                            Id=origin_id,
                            S3OriginConfig=cloudfront.S3OriginConfig(),
                            OriginAccessControlId=GetAtt(
                                bucket.cloudfront_oac_logical_id, "Id"
                            ),
                        )
                    ],
                    DefaultCacheBehavior=cloudfront.DefaultCacheBehavior(
                        TargetOriginId=origin_id,
                        ViewerProtocolPolicy="redirect-to-https",
                        AllowedMethods=["GET", "HEAD", "OPTIONS"],
                        CachedMethods=["GET", "HEAD"],
                        Compress=True,
                        ForwardedValues=cloudfront.ForwardedValues(
                            QueryString=False,
                            Cookies=cloudfront.Cookies(Forward="none"),
                        ),
                    ),
                    PriceClass="PriceClass_100",
                ),
                Tags=_resource_tags(context),
            )
        )
        root.add_resource(
            s3.BucketPolicy(
                bucket.bucket_policy_logical_id,
                Bucket=Ref(bucket.bucket_logical_id),
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "AllowCloudFrontRead",
                            "Effect": "Allow",
                            "Principal": {
                                "Service": "cloudfront.amazonaws.com"
                            },
                            "Action": "s3:GetObject",
                            "Resource": Sub(
                                f"${{{bucket.bucket_logical_id}.Arn}}/*"
                            ),
                            "Condition": {
                                "StringEquals": {
                                    "AWS:SourceArn": Sub(
                                        "arn:aws:cloudfront::"
                                        "${AWS::AccountId}:distribution/"
                                        f"${{{bucket.cloudfront_logical_id}}}"
                                    )
                                }
                            },
                        }
                    ],
                },
            )
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
    service_namespace = None
    if context.has_service_discovery:
        service_namespace = root.add_resource(
            servicediscovery.PrivateDnsNamespace(
                "ServiceNamespace",
                Condition="CreateServiceNamespace",
                Name=Sub(context.service_discovery_namespace_cfn),
                Vpc=Ref("VpcId"),
                Tags=_resource_tags(context),
            )
        )

    secrets_by_name = {secret.name: secret for secret in context.secrets}
    for secret in context.secrets:
        if secret.source.value == "generate":
            root.add_resource(
                secretsmanager.Secret(
                    secret.generated_secret_logical_id,
                    Name=Sub(
                        "/darth-infra/${ProjectName}/${EnvironmentName}/"
                        f"{secret.name}"
                    ),
                    GenerateSecretString=secretsmanager.GenerateSecretString(
                        PasswordLength=secret.length,
                        ExcludePunctuation=True,
                    ),
                    Tags=_resource_tags(context),
                )
            )

    rds_secret = None
    rds_security_group = None
    rds_secret_attachment = None
    if context.rds is not None:
        rds_secret = root.add_resource(
            secretsmanager.Secret(
                "RdsCredentialsSecret",
                Name=Sub("${ProjectName}-${EnvironmentName}-rds-credentials"),
                GenerateSecretString=If(
                    "HasRdsSnapshot",
                    Ref("AWS::NoValue"),
                    secretsmanager.GenerateSecretString(
                        SecretStringTemplate=(
                            '{"username": '
                            f'"{context.rds_master_username}"}}'
                        ),
                        GenerateStringKey="password",
                        PasswordLength=32,
                        ExcludeCharacters='"@/\\',
                    ),
                ),
                SecretString=If(
                    "HasRdsSnapshot",
                    Sub(
                        '{"username":"{{resolve:secretsmanager:'
                        '${SourceSecretArn}:SecretString:username}}",'
                        '"password":"{{resolve:secretsmanager:'
                        '${SourceSecretArn}:SecretString:password}}"}',
                        {"SourceSecretArn": Ref("RdsSourceSecretArn")},
                    ),
                    Ref("AWS::NoValue"),
                ),
                Tags=_resource_tags(context),
            )
        )
        rds_security_group = root.add_resource(
            ec2.SecurityGroup(
                "RdsSecurityGroup",
                GroupDescription=Sub("${ProjectName}-${EnvironmentName} rds"),
                VpcId=Ref("VpcId"),
                Tags=_resource_tags(context),
            )
        )
        rds_subnet_group = root.add_resource(
            rds.DBSubnetGroup(
                "RdsSubnetGroup",
                DBSubnetGroupDescription=Sub(
                    "${ProjectName}-${EnvironmentName} DB subnets"
                ),
                SubnetIds=Ref("PrivateSubnetIds"),
                Tags=_resource_tags(context),
            )
        )
        database = root.add_resource(
            rds.DBInstance(
                "Database",
                DeletionPolicy=If("IsProd", "Snapshot", "Delete"),
                UpdateReplacePolicy=If("IsProd", "Snapshot", "Delete"),
                DBInstanceIdentifier=Sub(
                    "${ProjectName}-${EnvironmentName}-db"
                ),
                DBInstanceClass=Ref("RdsInstanceType"),
                Engine="postgres",
                EngineVersion=context.rds.engine_version,
                MasterUsername=If(
                    "HasRdsSnapshot",
                    Ref("AWS::NoValue"),
                    Join(
                        "",
                        [
                            "{{resolve:secretsmanager:",
                            Ref(rds_secret),
                            ":SecretString:username}}",
                        ],
                    ),
                ),
                MasterUserPassword=If(
                    "HasRdsSnapshot",
                    Ref("AWS::NoValue"),
                    Join(
                        "",
                        [
                            "{{resolve:secretsmanager:",
                            Ref(rds_secret),
                            ":SecretString:password}}",
                        ],
                    ),
                ),
                AllocatedStorage=str(context.rds.allocated_storage_gb),
                BackupRetentionPeriod=context.rds.backup_retention_days,
                CopyTagsToSnapshot=True,
                DBName=If(
                    "HasRdsSnapshot",
                    Ref("AWS::NoValue"),
                    context.rds.database_name,
                ),
                DBSnapshotIdentifier=If(
                    "HasRdsSnapshot",
                    Ref("RdsSnapshotIdentifier"),
                    Ref("AWS::NoValue"),
                ),
                VPCSecurityGroups=[Ref(rds_security_group)],
                DBSubnetGroupName=Ref(rds_subnet_group),
                PubliclyAccessible=False,
                DeletionProtection=If("IsProd", True, False),
                StorageType="gp3",
                Tags=_resource_tags(context),
            )
        )
        rds_secret_attachment = root.add_resource(
            secretsmanager.SecretTargetAttachment(
                "RdsSecretAttachment",
                SecretId=Ref(rds_secret),
                TargetId=Ref(database),
                TargetType="AWS::RDS::DBInstance",
            )
        )

    dedicated_alb = root.add_resource(
        elasticloadbalancingv2.LoadBalancer(
            "DedicatedAlb",
            Condition="UseDedicatedAlb",
            Name=Sub("${ProjectName}-${EnvironmentName}-alb"),
            Scheme="internet-facing",
            SecurityGroups=[Ref("DedicatedAlbSecurityGroup")],
            Subnets=Ref("PublicSubnetIds"),
            Type="application",
            Tags=_resource_tags(context),
        )
    )
    root.add_resource(
        ec2.SecurityGroup(
            "DedicatedAlbSecurityGroup",
            Condition="UseDedicatedAlb",
            GroupDescription=Sub("${ProjectName}-${EnvironmentName} alb"),
            VpcId=Ref("VpcId"),
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort=80,
                    ToPort=80,
                    CidrIp="0.0.0.0/0",
                ),
                If(
                    "UseDedicatedAlbWithCert",
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "CidrIp": "0.0.0.0/0",
                    },
                    Ref("AWS::NoValue"),
                ),
            ],
            Tags=_resource_tags(context),
        )
    )
    http_listener = elasticloadbalancingv2.Listener(
        "DedicatedAlbHttpListener",
        Condition="UseDedicatedAlb",
        DefaultActions=[
            If(
                "UseDedicatedAlbWithCert",
                {
                    "Type": "redirect",
                    "RedirectConfig": {
                        "Protocol": "HTTPS",
                        "Port": "443",
                        "StatusCode": "HTTP_301",
                    },
                },
                {
                    "Type": "fixed-response",
                    "FixedResponseConfig": {
                        "StatusCode": "404",
                        "ContentType": "text/plain",
                        "MessageBody": "Not Found",
                    },
                },
            )
        ],
        LoadBalancerArn=Ref(dedicated_alb),
        Port=80,
        Protocol="HTTP",
    )
    root.add_resource(http_listener)
    https_listener = elasticloadbalancingv2.Listener(
        "DedicatedAlbHttpsListener",
        Condition="UseDedicatedAlbWithCert",
        Certificates=[
            elasticloadbalancingv2.Certificate(
                CertificateArn=Ref("CertificateArn")
            )
        ],
        DefaultActions=[
            elasticloadbalancingv2.Action(
                Type="fixed-response",
                FixedResponseConfig=elasticloadbalancingv2.FixedResponseConfig(
                    StatusCode="404",
                    ContentType="text/plain",
                    MessageBody="Not Found",
                ),
            )
        ],
        LoadBalancerArn=Ref(dedicated_alb),
        Port=443,
        Protocol="HTTPS",
    )
    root.add_resource(https_listener)

    if context.has_alb_cloudfront:
        root.add_resource(_build_alb_cloudfront(context))

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
            "AlbListenerArn": If(
                "UseDedicatedAlb",
                If(
                    "UseDedicatedAlbWithCert",
                    Ref(https_listener),
                    Ref(http_listener),
                ),
                Ref("SharedAlbListenerArn"),
            ),
            "AlbSecurityGroupId": If(
                "UseDedicatedAlb",
                Ref("DedicatedAlbSecurityGroup"),
                Ref("SharedAlbSecurityGroupId"),
            ),
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
        if service.has_rds:
            service_parameters["RdsSecretArn"] = Ref("RdsCredentialsSecret")
        if service.svc.enable_service_discovery:
            service_parameters["CloudMapNamespaceId"] = If(
                "HasExistingCloudMapNamespace",
                Ref("ExistingCloudMapNamespaceId"),
                Ref(service_namespace),
            )
        for s3_access in service.s3_vars:
            if s3_access.bucket_ref:
                service_parameters[s3_access.param_name] = Ref(
                    s3_access.bucket_ref
                )
                service_parameters[s3_access.arn_param_name] = GetAtt(
                    s3_access.bucket_ref, "Arn"
                )
            else:
                service_parameters[s3_access.param_name] = (
                    s3_access.bucket_name_literal
                )
                service_parameters[s3_access.arn_param_name] = Sub(
                    f"arn:aws:s3:::{s3_access.bucket_name_literal}"
                )
            if s3_access.fallback_param_name:
                service_parameters[s3_access.fallback_param_name] = (
                    s3_access.fallback_bucket_name_literal
                )
                service_parameters[s3_access.fallback_arn_param_name] = Sub(
                    "arn:aws:s3:::"
                    f"{s3_access.fallback_bucket_name_literal}"
                )
            if s3_access.cf_param_name:
                cloudfront_logical_id = (
                    f"CloudFront{s3_access.bucket_name.replace('-', '')}"
                )
                service_parameters[s3_access.cf_param_name] = Sub(
                    f"https://${{{cloudfront_logical_id}.DomainName}}"
                )
        for cloudfront_access in service.cloudfront_vars:
            service_parameters[cloudfront_access.param_name] = Sub(
                "https://${AlbCloudFront.DomainName}"
            )
        for secret in service.secret_params:
            if secret.source == "generate":
                secret_context = secrets_by_name[secret.secret_name]
                service_parameters[secret.param_name] = Ref(
                    secret_context.generated_secret_logical_id
                )
            elif secret.source in {"env", "existing"}:
                secret_context = secrets_by_name[secret.secret_name]
                service_parameters[secret.param_name] = Ref(
                    secret_context.external_parameter_name
                )
        service_stack = cloudformation.Stack(
            f"Service{service.name_pascal}",
            TemplateURL=f"services/{service.name}.yaml",
            Parameters=service_parameters,
            Tags=_resource_tags(context),
        )
        dependencies = []
        if service.has_rds and rds_secret_attachment is not None:
            dependencies.append(rds_secret_attachment.title)
        if repository is not None:
            dependencies.append(repository.title)
        if len(dependencies) == 1:
            service_stack.DependsOn = dependencies[0]
        elif dependencies:
            service_stack.DependsOn = dependencies
        root.add_resource(service_stack)

    if rds_security_group is not None:
        for service in context.services_ctx:
            if service.has_rds:
                root.add_resource(
                    ec2.SecurityGroupIngress(
                        f"RdsIngressFrom{service.name_pascal}",
                        GroupId=Ref(rds_security_group),
                        IpProtocol="tcp",
                        FromPort=5432,
                        ToPort=5432,
                        SourceSecurityGroupId=GetAtt(
                            f"Service{service.name_pascal}",
                            "Outputs.TaskSecurityGroupId",
                        ),
                    )
                )

    root.add_resource(
        route53.RecordSetType(
            "DnsRecord",
            Condition="HasHostedZone",
            HostedZoneId=Ref("HostedZoneId"),
            Name=Ref("ClusterDomain"),
            Type="A",
            AliasTarget=route53.AliasTarget(
                DNSName=If(
                    "UseDedicatedAlb",
                    GetAtt(dedicated_alb, "DNSName"),
                    Ref("SharedAlbDnsName"),
                ),
                HostedZoneId=If(
                    "UseDedicatedAlb",
                    GetAtt(dedicated_alb, "CanonicalHostedZoneID"),
                    Ref("SharedAlbCanonicalHostedZoneId"),
                ),
            ),
        )
    )
    root.add_resource(
        cloudformation.Stack(
            "CustomOverrides",
            TemplateURL="../custom/overrides.yaml",
            Tags=_resource_tags(context),
        )
    )
    root.add_output(Output("ClusterName", Value=Ref(cluster)))
    root.add_output(Output("StackEnvironment", Value=Ref("EnvironmentName")))
    root.add_output(
        Output(
            "AlbListenerArn",
            Value=If(
                "UseDedicatedAlb",
                If(
                    "UseDedicatedAlbWithCert",
                    Ref(https_listener),
                    Ref(http_listener),
                ),
                Ref("SharedAlbListenerArn"),
            ),
        )
    )
    if context.has_alb_cloudfront:
        root.add_output(
            Output("CloudFrontDistributionId", Value=Ref("AlbCloudFront"))
        )
        root.add_output(
            Output(
                "CloudFrontDomainName",
                Value=GetAtt("AlbCloudFront", "DomainName"),
            )
        )
        root.add_output(
            Output(
                "CloudFrontUrl",
                Value=Sub("https://${AlbCloudFront.DomainName}"),
            )
        )

    templates = {"templates/generated/root.yaml": root}
    for service in context.services_ctx:
        templates[f"templates/generated/services/{service.name}.yaml"] = (
            _build_service_template(context, service)
        )
    return templates


__all__ = ["ProjectTemplates", "build_project_templates"]
