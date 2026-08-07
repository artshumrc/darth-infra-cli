"""Frozen structural snapshots of built templates (the post-migration oracle).

These replace the former Jinja-render equivalence oracle used during the
expand phase of the troposphere migration. Each constant is a
``Template.to_dict()`` structure (dicts/lists/scalars only), so equality
comparison is formatting- and key-order-independent. Regenerate with the
scratchpad script if the builders intentionally change structure.
"""

MINIMAL_SERVICE = {
    "Description": "ECS service stack for demo/web",
    "Conditions": {
        "HasExtraTagEnvironmentType": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEnvironmentType"}, ""]}]
        },
        "HasExtraTagEphemeralCleanupId": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEphemeralCleanupId"}, ""]}]
        },
        "HasExtraTagPreviewBaseEnvironment": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPreviewBaseEnvironment"}, ""]}]
        },
        "HasExtraTagPullRequest": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPullRequest"}, ""]}]
        },
    },
    "Outputs": {
        "ServiceName": {"Value": {"Ref": "EcsService"}},
        "TaskSecurityGroupId": {"Value": {"Ref": "TaskSecurityGroup"}},
    },
    "Parameters": {
        "ProjectName": {"Type": "String"},
        "EnvironmentName": {"Type": "String"},
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "VpcCidr": {"Type": "String"},
        "PrivateSubnetIds": {"Type": "String"},
        "ClusterName": {"Type": "String"},
        "ClusterArn": {"Type": "String"},
        "ClusterDomain": {"Type": "String"},
        "AlbListenerArn": {"Type": "String"},
        "AlbSecurityGroupId": {"Type": "String"},
        "ExtraTagEnvironmentType": {"Type": "String", "Default": ""},
        "ExtraTagEphemeralCleanupId": {"Type": "String", "Default": ""},
        "ExtraTagPreviewBaseEnvironment": {"Type": "String", "Default": ""},
        "ExtraTagPullRequest": {"Type": "String", "Default": ""},
    },
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": {
        "LogGroup": {
            "Properties": {
                "LogGroupName": {
                    "Fn::Sub": "/ecs/${ProjectName}-${EnvironmentName}-web"
                },
                "RetentionInDays": 30,
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::Logs::LogGroup",
        },
        "TaskSecurityGroup": {
            "Properties": {
                "GroupDescription": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName}-web ecs tasks"
                },
                "VpcId": {"Ref": "VpcId"},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::EC2::SecurityGroup",
        },
        "TaskSgIngressFromAlb": {
            "Properties": {
                "GroupId": {"Ref": "TaskSecurityGroup"},
                "IpProtocol": -1,
                "CidrIp": "0.0.0.0/0",
            },
            "Type": "AWS::EC2::SecurityGroupEgress",
        },
        "TaskExecutionRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                ],
                "Policies": [],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "EcsExecSsm",
                        "PolicyDocument": {
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
                    }
                ],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskDefinition": {
            "Properties": {
                "Family": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "ExecutionRoleArn": {"Fn::GetAtt": ["TaskExecutionRole", "Arn"]},
                "TaskRoleArn": {"Fn::GetAtt": ["TaskRole", "Arn"]},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "ContainerDefinitions": [
                    {
                        "Name": "web",
                        "Image": {
                            "Fn::Sub": "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ProjectName}/${EnvironmentName}/web:latest"
                        },
                        "Essential": True,
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": {"Ref": "LogGroup"},
                                "awslogs-region": {"Ref": "AWS::Region"},
                                "awslogs-stream-prefix": "web",
                            },
                        },
                        "Environment": [
                            {
                                "Name": "ENVIRONMENT",
                                "Value": {"Ref": "EnvironmentName"},
                            },
                            {"Name": "SERVICE_NAME", "Value": "web"},
                        ],
                        "PortMappings": [{"ContainerPort": 8000, "Protocol": "tcp"}],
                    }
                ],
                "Cpu": "256",
                "Memory": "512",
            },
            "Type": "AWS::ECS::TaskDefinition",
        },
        "EcsService": {
            "Properties": {
                "ServiceName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "Cluster": {"Ref": "ClusterArn"},
                "DesiredCount": 1,
                "EnableExecuteCommand": True,
                "LaunchType": "FARGATE",
                "TaskDefinition": {"Ref": "TaskDefinition"},
                "PropagateTags": "TASK_DEFINITION",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "AssignPublicIp": "DISABLED",
                        "SecurityGroups": [{"Ref": "TaskSecurityGroup"}],
                        "Subnets": {"Fn::Split": [",", {"Ref": "PrivateSubnetIds"}]},
                    }
                },
            },
            "Type": "AWS::ECS::Service",
            "DependsOn": ["TaskDefinition"],
        },
    },
}

SHARED_ALB_SERVICE = {
    "Description": "ECS service stack for demo/web",
    "Conditions": {
        "HasExtraTagEnvironmentType": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEnvironmentType"}, ""]}]
        },
        "HasExtraTagEphemeralCleanupId": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEphemeralCleanupId"}, ""]}]
        },
        "HasExtraTagPreviewBaseEnvironment": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPreviewBaseEnvironment"}, ""]}]
        },
        "HasExtraTagPullRequest": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPullRequest"}, ""]}]
        },
    },
    "Outputs": {
        "ServiceName": {"Value": {"Ref": "EcsService"}},
        "TaskSecurityGroupId": {"Value": {"Ref": "TaskSecurityGroup"}},
        "TargetGroupArn": {"Value": {"Ref": "TargetGroup"}},
    },
    "Parameters": {
        "ProjectName": {"Type": "String"},
        "EnvironmentName": {"Type": "String"},
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "VpcCidr": {"Type": "String"},
        "PrivateSubnetIds": {"Type": "String"},
        "ClusterName": {"Type": "String"},
        "ClusterArn": {"Type": "String"},
        "ClusterDomain": {"Type": "String"},
        "AlbListenerArn": {"Type": "String"},
        "AlbSecurityGroupId": {"Type": "String"},
        "DefaultListenerPriority": {"Type": "Number"},
        "PathRulePriorityApiV2": {"Type": "Number"},
        "ExtraTagEnvironmentType": {"Type": "String", "Default": ""},
        "ExtraTagEphemeralCleanupId": {"Type": "String", "Default": ""},
        "ExtraTagPreviewBaseEnvironment": {"Type": "String", "Default": ""},
        "ExtraTagPullRequest": {"Type": "String", "Default": ""},
    },
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": {
        "LogGroup": {
            "Properties": {
                "LogGroupName": {
                    "Fn::Sub": "/ecs/${ProjectName}-${EnvironmentName}-web"
                },
                "RetentionInDays": 30,
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::Logs::LogGroup",
        },
        "TaskSecurityGroup": {
            "Properties": {
                "GroupDescription": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName}-web ecs tasks"
                },
                "VpcId": {"Ref": "VpcId"},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::EC2::SecurityGroup",
        },
        "TaskSgIngressFromAlb": {
            "Properties": {
                "GroupId": {"Ref": "TaskSecurityGroup"},
                "IpProtocol": "tcp",
                "FromPort": 8000,
                "ToPort": 8000,
                "SourceSecurityGroupId": {"Ref": "AlbSecurityGroupId"},
            },
            "Type": "AWS::EC2::SecurityGroupIngress",
        },
        "TaskExecutionRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                ],
                "Policies": [],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "EcsExecSsm",
                        "PolicyDocument": {
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
                    }
                ],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskDefinition": {
            "Properties": {
                "Family": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "ExecutionRoleArn": {"Fn::GetAtt": ["TaskExecutionRole", "Arn"]},
                "TaskRoleArn": {"Fn::GetAtt": ["TaskRole", "Arn"]},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "ContainerDefinitions": [
                    {
                        "Name": "web",
                        "Image": {
                            "Fn::Sub": "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ProjectName}/${EnvironmentName}/web:latest"
                        },
                        "Essential": True,
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": {"Ref": "LogGroup"},
                                "awslogs-region": {"Ref": "AWS::Region"},
                                "awslogs-stream-prefix": "web",
                            },
                        },
                        "Environment": [
                            {
                                "Name": "ENVIRONMENT",
                                "Value": {"Ref": "EnvironmentName"},
                            },
                            {"Name": "SERVICE_NAME", "Value": "web"},
                        ],
                        "PortMappings": [{"ContainerPort": 8000, "Protocol": "tcp"}],
                    }
                ],
                "Cpu": "256",
                "Memory": "512",
            },
            "Type": "AWS::ECS::TaskDefinition",
        },
        "TargetGroup": {
            "Properties": {
                "Port": 8000,
                "Protocol": "HTTP",
                "TargetType": "ip",
                "VpcId": {"Ref": "VpcId"},
                "HealthCheckPath": "/health",
                "HealthCheckTimeoutSeconds": 5,
                "HealthCheckIntervalSeconds": 30,
                "HealthyThresholdCount": 5,
                "UnhealthyThresholdCount": 2,
                "Matcher": {"HttpCode": "200-399"},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::ElasticLoadBalancingV2::TargetGroup",
        },
        "DefaultHostHeaderRule": {
            "Properties": {
                "Actions": [
                    {"Type": "forward", "TargetGroupArn": {"Ref": "TargetGroup"}}
                ],
                "Conditions": [
                    {
                        "Field": "host-header",
                        "HostHeaderConfig": {"Values": [{"Ref": "ClusterDomain"}]},
                    }
                ],
                "ListenerArn": {"Ref": "AlbListenerArn"},
                "Priority": {"Ref": "DefaultListenerPriority"},
            },
            "Type": "AWS::ElasticLoadBalancingV2::ListenerRule",
        },
        "PathRuleApiV2": {
            "Properties": {
                "Actions": [
                    {"Type": "forward", "TargetGroupArn": {"Ref": "TargetGroup"}}
                ],
                "Conditions": [
                    {
                        "Field": "host-header",
                        "HostHeaderConfig": {"Values": [{"Ref": "ClusterDomain"}]},
                    },
                    {
                        "Field": "path-pattern",
                        "PathPatternConfig": {"Values": ["/api/v2/*"]},
                    },
                ],
                "ListenerArn": {"Ref": "AlbListenerArn"},
                "Priority": {"Ref": "PathRulePriorityApiV2"},
            },
            "Type": "AWS::ElasticLoadBalancingV2::ListenerRule",
        },
        "EcsService": {
            "Properties": {
                "ServiceName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "Cluster": {"Ref": "ClusterArn"},
                "DesiredCount": 1,
                "EnableExecuteCommand": True,
                "LaunchType": "FARGATE",
                "TaskDefinition": {"Ref": "TaskDefinition"},
                "PropagateTags": "TASK_DEFINITION",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "AssignPublicIp": "DISABLED",
                        "SecurityGroups": [{"Ref": "TaskSecurityGroup"}],
                        "Subnets": {"Fn::Split": [",", {"Ref": "PrivateSubnetIds"}]},
                    }
                },
                "LoadBalancers": [
                    {
                        "ContainerName": "web",
                        "ContainerPort": 8000,
                        "TargetGroupArn": {"Ref": "TargetGroup"},
                    }
                ],
            },
            "Type": "AWS::ECS::Service",
            "DependsOn": ["TaskDefinition", "DefaultHostHeaderRule", "PathRuleApiV2"],
        },
    },
}

SERVICE_DISCOVERY_SERVICE = {
    "Description": "ECS service stack for demo/web",
    "Conditions": {
        "HasExtraTagEnvironmentType": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEnvironmentType"}, ""]}]
        },
        "HasExtraTagEphemeralCleanupId": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEphemeralCleanupId"}, ""]}]
        },
        "HasExtraTagPreviewBaseEnvironment": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPreviewBaseEnvironment"}, ""]}]
        },
        "HasExtraTagPullRequest": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPullRequest"}, ""]}]
        },
    },
    "Outputs": {
        "ServiceName": {"Value": {"Ref": "EcsService"}},
        "TaskSecurityGroupId": {"Value": {"Ref": "TaskSecurityGroup"}},
    },
    "Parameters": {
        "ProjectName": {"Type": "String"},
        "EnvironmentName": {"Type": "String"},
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "VpcCidr": {"Type": "String"},
        "PrivateSubnetIds": {"Type": "String"},
        "ClusterName": {"Type": "String"},
        "ClusterArn": {"Type": "String"},
        "ClusterDomain": {"Type": "String"},
        "AlbListenerArn": {"Type": "String"},
        "AlbSecurityGroupId": {"Type": "String"},
        "ExtraTagEnvironmentType": {"Type": "String", "Default": ""},
        "ExtraTagEphemeralCleanupId": {"Type": "String", "Default": ""},
        "ExtraTagPreviewBaseEnvironment": {"Type": "String", "Default": ""},
        "ExtraTagPullRequest": {"Type": "String", "Default": ""},
        "CloudMapNamespaceId": {"Type": "String"},
    },
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": {
        "LogGroup": {
            "Properties": {
                "LogGroupName": {
                    "Fn::Sub": "/ecs/${ProjectName}-${EnvironmentName}-web"
                },
                "RetentionInDays": 30,
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::Logs::LogGroup",
        },
        "TaskSecurityGroup": {
            "Properties": {
                "GroupDescription": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName}-web ecs tasks"
                },
                "VpcId": {"Ref": "VpcId"},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::EC2::SecurityGroup",
        },
        "TaskSgIngressFromAlb": {
            "Properties": {
                "GroupId": {"Ref": "TaskSecurityGroup"},
                "IpProtocol": -1,
                "CidrIp": "0.0.0.0/0",
            },
            "Type": "AWS::EC2::SecurityGroupEgress",
        },
        "TaskSgIngressFromServiceDiscovery": {
            "Properties": {
                "GroupId": {"Ref": "TaskSecurityGroup"},
                "IpProtocol": "tcp",
                "FromPort": 8000,
                "ToPort": 8000,
                "CidrIp": {"Ref": "VpcCidr"},
            },
            "Type": "AWS::EC2::SecurityGroupIngress",
        },
        "TaskExecutionRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                ],
                "Policies": [],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "EcsExecSsm",
                        "PolicyDocument": {
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
                    }
                ],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskDefinition": {
            "Properties": {
                "Family": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "ExecutionRoleArn": {"Fn::GetAtt": ["TaskExecutionRole", "Arn"]},
                "TaskRoleArn": {"Fn::GetAtt": ["TaskRole", "Arn"]},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "ContainerDefinitions": [
                    {
                        "Name": "web",
                        "Image": {
                            "Fn::Sub": "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ProjectName}/${EnvironmentName}/web:latest"
                        },
                        "Essential": True,
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": {"Ref": "LogGroup"},
                                "awslogs-region": {"Ref": "AWS::Region"},
                                "awslogs-stream-prefix": "web",
                            },
                        },
                        "Environment": [
                            {
                                "Name": "ENVIRONMENT",
                                "Value": {"Ref": "EnvironmentName"},
                            },
                            {"Name": "SERVICE_NAME", "Value": "web"},
                        ],
                        "PortMappings": [{"ContainerPort": 8000, "Protocol": "tcp"}],
                    }
                ],
                "Cpu": "256",
                "Memory": "512",
            },
            "Type": "AWS::ECS::TaskDefinition",
        },
        "CloudMapService": {
            "Properties": {
                "Name": "web",
                "NamespaceId": {"Ref": "CloudMapNamespaceId"},
                "DnsConfig": {"DnsRecords": [{"Type": "A", "TTL": 10}]},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::ServiceDiscovery::Service",
        },
        "EcsService": {
            "Properties": {
                "ServiceName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "Cluster": {"Ref": "ClusterArn"},
                "DesiredCount": 1,
                "EnableExecuteCommand": True,
                "LaunchType": "FARGATE",
                "TaskDefinition": {"Ref": "TaskDefinition"},
                "PropagateTags": "TASK_DEFINITION",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "AssignPublicIp": "DISABLED",
                        "SecurityGroups": [{"Ref": "TaskSecurityGroup"}],
                        "Subnets": {"Fn::Split": [",", {"Ref": "PrivateSubnetIds"}]},
                    }
                },
                "ServiceRegistries": [
                    {"RegistryArn": {"Fn::GetAtt": ["CloudMapService", "Arn"]}}
                ],
            },
            "Type": "AWS::ECS::Service",
            "DependsOn": ["TaskDefinition"],
        },
    },
}

S3_SERVICE = {
    "Description": "ECS service stack for demo/web",
    "Conditions": {
        "HasExtraTagEnvironmentType": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEnvironmentType"}, ""]}]
        },
        "HasExtraTagEphemeralCleanupId": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagEphemeralCleanupId"}, ""]}]
        },
        "HasExtraTagPreviewBaseEnvironment": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPreviewBaseEnvironment"}, ""]}]
        },
        "HasExtraTagPullRequest": {
            "Fn::Not": [{"Fn::Equals": [{"Ref": "ExtraTagPullRequest"}, ""]}]
        },
    },
    "Outputs": {
        "ServiceName": {"Value": {"Ref": "EcsService"}},
        "TaskSecurityGroupId": {"Value": {"Ref": "TaskSecurityGroup"}},
    },
    "Parameters": {
        "ProjectName": {"Type": "String"},
        "EnvironmentName": {"Type": "String"},
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "VpcCidr": {"Type": "String"},
        "PrivateSubnetIds": {"Type": "String"},
        "ClusterName": {"Type": "String"},
        "ClusterArn": {"Type": "String"},
        "ClusterDomain": {"Type": "String"},
        "AlbListenerArn": {"Type": "String"},
        "AlbSecurityGroupId": {"Type": "String"},
        "ExtraTagEnvironmentType": {"Type": "String", "Default": ""},
        "ExtraTagEphemeralCleanupId": {"Type": "String", "Default": ""},
        "ExtraTagPreviewBaseEnvironment": {"Type": "String", "Default": ""},
        "ExtraTagPullRequest": {"Type": "String", "Default": ""},
        "BucketNameMediaFiles": {"Type": "String"},
        "BucketArnMediaFiles": {"Type": "String"},
        "BucketNameSharedAssets": {"Type": "String"},
        "BucketArnSharedAssets": {"Type": "String"},
    },
    "AWSTemplateFormatVersion": "2010-09-09",
    "Resources": {
        "LogGroup": {
            "Properties": {
                "LogGroupName": {
                    "Fn::Sub": "/ecs/${ProjectName}-${EnvironmentName}-web"
                },
                "RetentionInDays": 30,
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::Logs::LogGroup",
        },
        "TaskSecurityGroup": {
            "Properties": {
                "GroupDescription": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName}-web ecs tasks"
                },
                "VpcId": {"Ref": "VpcId"},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::EC2::SecurityGroup",
        },
        "TaskSgIngressFromAlb": {
            "Properties": {
                "GroupId": {"Ref": "TaskSecurityGroup"},
                "IpProtocol": -1,
                "CidrIp": "0.0.0.0/0",
            },
            "Type": "AWS::EC2::SecurityGroupEgress",
        },
        "TaskExecutionRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                ],
                "Policies": [],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskRole": {
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "EcsExecSsm",
                        "PolicyDocument": {
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
                    },
                    {
                        "PolicyName": "S3Access",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "s3:GetObject",
                                        "s3:PutObject",
                                        "s3:DeleteObject",
                                        "s3:ListBucket",
                                    ],
                                    "Resource": [
                                        {"Ref": "BucketArnMediaFiles"},
                                        {
                                            "Fn::Join": [
                                                "",
                                                [{"Ref": "BucketArnMediaFiles"}, "/*"],
                                            ]
                                        },
                                    ],
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject", "s3:ListBucket"],
                                    "Resource": [
                                        {"Ref": "BucketArnSharedAssets"},
                                        {
                                            "Fn::Join": [
                                                "",
                                                [
                                                    {"Ref": "BucketArnSharedAssets"},
                                                    "/*",
                                                ],
                                            ]
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                ],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::IAM::Role",
        },
        "TaskDefinition": {
            "Properties": {
                "Family": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "ExecutionRoleArn": {"Fn::GetAtt": ["TaskExecutionRole", "Arn"]},
                "TaskRoleArn": {"Fn::GetAtt": ["TaskRole", "Arn"]},
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "ContainerDefinitions": [
                    {
                        "Name": "web",
                        "Image": {
                            "Fn::Sub": "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ProjectName}/${EnvironmentName}/web:latest"
                        },
                        "Essential": True,
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": {"Ref": "LogGroup"},
                                "awslogs-region": {"Ref": "AWS::Region"},
                                "awslogs-stream-prefix": "web",
                            },
                        },
                        "Environment": [
                            {
                                "Name": "ENVIRONMENT",
                                "Value": {"Ref": "EnvironmentName"},
                            },
                            {"Name": "SERVICE_NAME", "Value": "web"},
                            {
                                "Name": "MEDIA_BUCKET",
                                "Value": {"Ref": "BucketNameMediaFiles"},
                            },
                            {
                                "Name": "SHARED_ASSETS_BUCKET",
                                "Value": {"Ref": "BucketNameSharedAssets"},
                            },
                        ],
                        "PortMappings": [{"ContainerPort": 8000, "Protocol": "tcp"}],
                    }
                ],
                "Cpu": "256",
                "Memory": "512",
            },
            "Type": "AWS::ECS::TaskDefinition",
        },
        "EcsService": {
            "Properties": {
                "ServiceName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-web"},
                "Cluster": {"Ref": "ClusterArn"},
                "DesiredCount": 1,
                "EnableExecuteCommand": True,
                "LaunchType": "FARGATE",
                "TaskDefinition": {"Ref": "TaskDefinition"},
                "PropagateTags": "TASK_DEFINITION",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {"Key": "Service", "Value": "web"},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "AssignPublicIp": "DISABLED",
                        "SecurityGroups": [{"Ref": "TaskSecurityGroup"}],
                        "Subnets": {"Fn::Split": [",", {"Ref": "PrivateSubnetIds"}]},
                    }
                },
            },
            "Type": "AWS::ECS::Service",
            "DependsOn": ["TaskDefinition"],
        },
    },
}

DEDICATED_ALB_ROOT = {
    "Resources": {
        "DedicatedAlb": {
            "Properties": {
                "Name": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-alb"},
                "Scheme": "internet-facing",
                "SecurityGroups": [{"Ref": "DedicatedAlbSecurityGroup"}],
                "Subnets": {"Ref": "PublicSubnetIds"},
                "Type": "application",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "Condition": "UseDedicatedAlb",
        },
        "DedicatedAlbSecurityGroup": {
            "Properties": {
                "GroupDescription": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName} alb"
                },
                "VpcId": {"Ref": "VpcId"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 80,
                        "ToPort": 80,
                        "CidrIp": "0.0.0.0/0",
                    },
                    {
                        "Fn::If": [
                            "UseDedicatedAlbWithCert",
                            {
                                "IpProtocol": "tcp",
                                "FromPort": 443,
                                "ToPort": 443,
                                "CidrIp": "0.0.0.0/0",
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::EC2::SecurityGroup",
            "Condition": "UseDedicatedAlb",
        },
        "DedicatedAlbHttpListener": {
            "Properties": {
                "DefaultActions": [
                    {
                        "Fn::If": [
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
                        ]
                    }
                ],
                "LoadBalancerArn": {"Ref": "DedicatedAlb"},
                "Port": 80,
                "Protocol": "HTTP",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::ElasticLoadBalancingV2::Listener",
            "Condition": "UseDedicatedAlb",
        },
        "DedicatedAlbHttpsListener": {
            "Properties": {
                "Certificates": [{"CertificateArn": {"Ref": "CertificateArn"}}],
                "DefaultActions": [
                    {
                        "Type": "fixed-response",
                        "FixedResponseConfig": {
                            "StatusCode": "404",
                            "ContentType": "text/plain",
                            "MessageBody": "Not Found",
                        },
                    }
                ],
                "LoadBalancerArn": {"Ref": "DedicatedAlb"},
                "Port": 443,
                "Protocol": "HTTPS",
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::ElasticLoadBalancingV2::Listener",
            "Condition": "UseDedicatedAlbWithCert",
        },
        "DnsRecord": {
            "Properties": {
                "HostedZoneId": {"Ref": "HostedZoneId"},
                "Name": {"Ref": "ClusterDomain"},
                "Type": "A",
                "AliasTarget": {
                    "DNSName": {
                        "Fn::If": [
                            "UseDedicatedAlb",
                            {"Fn::GetAtt": ["DedicatedAlb", "DNSName"]},
                            {"Ref": "SharedAlbDnsName"},
                        ]
                    },
                    "HostedZoneId": {
                        "Fn::If": [
                            "UseDedicatedAlb",
                            {"Fn::GetAtt": ["DedicatedAlb", "CanonicalHostedZoneID"]},
                            {"Ref": "SharedAlbCanonicalHostedZoneId"},
                        ]
                    },
                },
            },
            "Type": "AWS::Route53::RecordSet",
            "Condition": "HasHostedZone",
        },
        "ServiceWeb": {
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
                    "ExtraTagEnvironmentType": {"Ref": "ExtraTagEnvironmentType"},
                    "ExtraTagEphemeralCleanupId": {"Ref": "ExtraTagEphemeralCleanupId"},
                    "ExtraTagPreviewBaseEnvironment": {
                        "Ref": "ExtraTagPreviewBaseEnvironment"
                    },
                    "ExtraTagPullRequest": {"Ref": "ExtraTagPullRequest"},
                    "DefaultListenerPriority": {"Ref": "DefaultListenerPriority"},
                },
                "Tags": [
                    {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                    {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                    {
                        "Fn::If": [
                            "HasExtraTagEnvironmentType",
                            {
                                "Key": "environment-type",
                                "Value": {"Ref": "ExtraTagEnvironmentType"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagEphemeralCleanupId",
                            {
                                "Key": "ephemeral-cleanup-id",
                                "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPreviewBaseEnvironment",
                            {
                                "Key": "preview-base-environment",
                                "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                    {
                        "Fn::If": [
                            "HasExtraTagPullRequest",
                            {
                                "Key": "pull-request",
                                "Value": {"Ref": "ExtraTagPullRequest"},
                            },
                            {"Ref": "AWS::NoValue"},
                        ]
                    },
                ],
            },
            "Type": "AWS::CloudFormation::Stack",
            "DependsOn": "EcrRepoWeb",
        },
    },
    "Outputs": {
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
        }
    },
}

DEDICATED_ALB_NOCERT = {
    "Conditions": {
        "UseDedicatedAlbNoCert": {
            "Fn::And": [
                {"Condition": "UseDedicatedAlb"},
                {"Fn::Not": [{"Condition": "HasCertificate"}]},
            ]
        }
    },
    "DedicatedAlbHttpListener": {
        "Properties": {
            "DefaultActions": [
                {
                    "Fn::If": [
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
                    ]
                }
            ],
            "LoadBalancerArn": {"Ref": "DedicatedAlb"},
            "Port": 80,
            "Protocol": "HTTP",
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::ElasticLoadBalancingV2::Listener",
        "Condition": "UseDedicatedAlb",
    },
}

RDS_ROOT_RESOURCES = {
    "SecretAPPSECRET": {
        "Properties": {
            "Name": {
                "Fn::Sub": "/darth-infra/${ProjectName}/${EnvironmentName}/APP_SECRET"
            },
            "GenerateSecretString": {"PasswordLength": 50, "ExcludePunctuation": True},
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::SecretsManager::Secret",
    },
    "RdsCredentialsSecret": {
        "Properties": {
            "Name": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-rds-credentials"},
            "GenerateSecretString": {
                "Fn::If": [
                    "HasRdsSnapshot",
                    {"Ref": "AWS::NoValue"},
                    {
                        "SecretStringTemplate": '{"username": "demodb"}',
                        "GenerateStringKey": "password",
                        "PasswordLength": 32,
                        "ExcludeCharacters": '"@/\\',
                    },
                ]
            },
            "SecretString": {
                "Fn::If": [
                    "HasRdsSnapshot",
                    {
                        "Fn::Sub": [
                            '{"username":"{{resolve:secretsmanager:${SourceSecretArn}:SecretString:username}}","password":"{{resolve:secretsmanager:${SourceSecretArn}:SecretString:password}}"}',
                            {"SourceSecretArn": {"Ref": "RdsSourceSecretArn"}},
                        ]
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::SecretsManager::Secret",
    },
    "RdsSecurityGroup": {
        "Properties": {
            "GroupDescription": {"Fn::Sub": "${ProjectName}-${EnvironmentName} rds"},
            "VpcId": {"Ref": "VpcId"},
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::EC2::SecurityGroup",
    },
    "RdsSubnetGroup": {
        "Properties": {
            "DBSubnetGroupDescription": {
                "Fn::Sub": "${ProjectName}-${EnvironmentName} DB subnets"
            },
            "SubnetIds": {"Ref": "PrivateSubnetIds"},
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::RDS::DBSubnetGroup",
    },
    "Database": {
        "Properties": {
            "DBInstanceIdentifier": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-db"},
            "DBInstanceClass": {"Ref": "RdsInstanceType"},
            "Engine": "postgres",
            "EngineVersion": "16",
            "MasterUsername": {
                "Fn::If": [
                    "HasRdsSnapshot",
                    {"Ref": "AWS::NoValue"},
                    {
                        "Fn::Join": [
                            "",
                            [
                                "{{resolve:secretsmanager:",
                                {"Ref": "RdsCredentialsSecret"},
                                ":SecretString:username}}",
                            ],
                        ]
                    },
                ]
            },
            "MasterUserPassword": {
                "Fn::If": [
                    "HasRdsSnapshot",
                    {"Ref": "AWS::NoValue"},
                    {
                        "Fn::Join": [
                            "",
                            [
                                "{{resolve:secretsmanager:",
                                {"Ref": "RdsCredentialsSecret"},
                                ":SecretString:password}}",
                            ],
                        ]
                    },
                ]
            },
            "AllocatedStorage": "30",
            "BackupRetentionPeriod": 14,
            "CopyTagsToSnapshot": True,
            "DBName": {
                "Fn::If": ["HasRdsSnapshot", {"Ref": "AWS::NoValue"}, "demo_db"]
            },
            "DBSnapshotIdentifier": {
                "Fn::If": [
                    "HasRdsSnapshot",
                    {"Ref": "RdsSnapshotIdentifier"},
                    {"Ref": "AWS::NoValue"},
                ]
            },
            "VPCSecurityGroups": [{"Ref": "RdsSecurityGroup"}],
            "DBSubnetGroupName": {"Ref": "RdsSubnetGroup"},
            "PubliclyAccessible": False,
            "DeletionProtection": {"Fn::If": ["IsProd", True, False]},
            "StorageType": "gp3",
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::RDS::DBInstance",
        "DeletionPolicy": {"Fn::If": ["IsProd", "Snapshot", "Delete"]},
        "UpdateReplacePolicy": {"Fn::If": ["IsProd", "Snapshot", "Delete"]},
    },
    "RdsSecretAttachment": {
        "Properties": {
            "SecretId": {"Ref": "RdsCredentialsSecret"},
            "TargetId": {"Ref": "Database"},
            "TargetType": "AWS::RDS::DBInstance",
        },
        "Type": "AWS::SecretsManager::SecretTargetAttachment",
    },
    "ServiceWeb": {
        "Properties": {
            "TemplateURL": "services/web.yaml",
            "Parameters": {
                "ProjectName": {"Ref": "ProjectName"},
                "EnvironmentName": {"Ref": "EnvironmentName"},
                "VpcId": {"Ref": "VpcId"},
                "VpcCidr": {"Ref": "VpcCidr"},
                "PrivateSubnetIds": {"Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]},
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
                "ExtraTagEnvironmentType": {"Ref": "ExtraTagEnvironmentType"},
                "ExtraTagEphemeralCleanupId": {"Ref": "ExtraTagEphemeralCleanupId"},
                "ExtraTagPreviewBaseEnvironment": {
                    "Ref": "ExtraTagPreviewBaseEnvironment"
                },
                "ExtraTagPullRequest": {"Ref": "ExtraTagPullRequest"},
                "RdsSecretArn": {"Ref": "RdsCredentialsSecret"},
                "SecretArnAPPSECRET": {"Ref": "SecretAPPSECRET"},
                "SecretArnEXISTINGTOKEN": {"Ref": "EnvSecretArnEXISTINGTOKEN"},
                "SecretArnENVTOKEN": {"Ref": "EnvSecretArnENVTOKEN"},
            },
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::CloudFormation::Stack",
        "DependsOn": ["RdsSecretAttachment", "EcrRepoWeb"],
    },
    "RdsIngressFromWeb": {
        "Properties": {
            "GroupId": {"Ref": "RdsSecurityGroup"},
            "IpProtocol": "tcp",
            "FromPort": 5432,
            "ToPort": 5432,
            "SourceSecurityGroupId": {
                "Fn::GetAtt": ["ServiceWeb", "Outputs.TaskSecurityGroupId"]
            },
        },
        "Type": "AWS::EC2::SecurityGroupIngress",
    },
}

SERVICE_DISCOVERY_ROOT_NAMESPACE = {
    "Properties": {
        "Name": {"Fn::Sub": "${ProjectName}-${EnvironmentName}.local"},
        "Vpc": {"Ref": "VpcId"},
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
    },
    "Type": "AWS::ServiceDiscovery::PrivateDnsNamespace",
    "Condition": "CreateServiceNamespace",
}

SERVICE_DISCOVERY_ROOT_SERVICEWEB = {
    "Properties": {
        "TemplateURL": "services/web.yaml",
        "Parameters": {
            "ProjectName": {"Ref": "ProjectName"},
            "EnvironmentName": {"Ref": "EnvironmentName"},
            "VpcId": {"Ref": "VpcId"},
            "VpcCidr": {"Ref": "VpcCidr"},
            "PrivateSubnetIds": {"Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]},
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
            "ExtraTagEnvironmentType": {"Ref": "ExtraTagEnvironmentType"},
            "ExtraTagEphemeralCleanupId": {"Ref": "ExtraTagEphemeralCleanupId"},
            "ExtraTagPreviewBaseEnvironment": {"Ref": "ExtraTagPreviewBaseEnvironment"},
            "ExtraTagPullRequest": {"Ref": "ExtraTagPullRequest"},
            "CloudMapNamespaceId": {
                "Fn::If": [
                    "HasExistingCloudMapNamespace",
                    {"Ref": "ExistingCloudMapNamespaceId"},
                    {"Ref": "ServiceNamespace"},
                ]
            },
        },
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
    },
    "Type": "AWS::CloudFormation::Stack",
    "DependsOn": "EcrRepoWeb",
}

S3_ROOT_BUCKET_MEDIAFILES = {
    "Properties": {
        "BucketName": {"Fn::Sub": "${ProjectName}-${EnvironmentName}-media-files"},
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
        "CorsConfiguration": {
            "CorsRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                    "AllowedOrigins": ["*"],
                }
            ]
        },
    },
    "Type": "AWS::S3::Bucket",
}

S3_ROOT_SERVICEWEB = {
    "Properties": {
        "TemplateURL": "services/web.yaml",
        "Parameters": {
            "ProjectName": {"Ref": "ProjectName"},
            "EnvironmentName": {"Ref": "EnvironmentName"},
            "VpcId": {"Ref": "VpcId"},
            "VpcCidr": {"Ref": "VpcCidr"},
            "PrivateSubnetIds": {"Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]},
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
            "ExtraTagEnvironmentType": {"Ref": "ExtraTagEnvironmentType"},
            "ExtraTagEphemeralCleanupId": {"Ref": "ExtraTagEphemeralCleanupId"},
            "ExtraTagPreviewBaseEnvironment": {"Ref": "ExtraTagPreviewBaseEnvironment"},
            "ExtraTagPullRequest": {"Ref": "ExtraTagPullRequest"},
            "BucketNameMediaFiles": {"Ref": "Bucketmediafiles"},
            "BucketArnMediaFiles": {"Fn::GetAtt": ["Bucketmediafiles", "Arn"]},
            "BucketNameSharedAssets": "company-shared-assets",
            "BucketArnSharedAssets": {"Fn::Sub": "arn:aws:s3:::company-shared-assets"},
        },
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
    },
    "Type": "AWS::CloudFormation::Stack",
    "DependsOn": "EcrRepoWeb",
}

CF_CUSTOM_DOMAIN = {
    "AlbCloudFront": {
        "Properties": {
            "DistributionConfig": {
                "Enabled": True,
                "PriceClass": "PriceClass_100",
                "Origins": [
                    {
                        "DomainName": {
                            "Fn::If": [
                                "UseDedicatedAlb",
                                {"Fn::GetAtt": ["DedicatedAlb", "DNSName"]},
                                {"Ref": "SharedAlbDnsName"},
                            ]
                        },
                        "Id": "AlbOrigin",
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "HTTPSPort": 443,
                            "OriginProtocolPolicy": "https-only",
                        },
                    }
                ],
                "DefaultCacheBehavior": {
                    "TargetOriginId": "AlbOrigin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": [
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "PATCH",
                        "POST",
                        "DELETE",
                    ],
                    "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                    "Compress": True,
                    "MinTTL": 0,
                    "DefaultTTL": 0,
                    "MaxTTL": 0,
                    "ForwardedValues": {
                        "QueryString": True,
                        "Cookies": {"Forward": "all"},
                        "Headers": ["*"],
                    },
                },
                "Aliases": ["cdn.example.com"],
                "ViewerCertificate": {
                    "AcmCertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555",
                    "SslSupportMethod": "sni-only",
                    "MinimumProtocolVersion": "TLSv1.2_2021",
                },
                "CacheBehaviors": [
                    {
                        "PathPattern": "/iiif/*",
                        "TargetOriginId": "AlbOrigin",
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": [
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "PUT",
                            "PATCH",
                            "POST",
                            "DELETE",
                        ],
                        "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                        "Compress": True,
                        "MinTTL": 0,
                        "DefaultTTL": 3600,
                        "MaxTTL": 31536000,
                        "ForwardedValues": {
                            "QueryString": True,
                            "Cookies": {"Forward": "none"},
                            "Headers": ["Host", "Authorization"],
                        },
                    }
                ],
            },
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::CloudFront::Distribution",
    },
    "Outputs": {
        "CloudFrontDistributionId": {"Value": {"Ref": "AlbCloudFront"}},
        "CloudFrontDomainName": {
            "Value": {"Fn::GetAtt": ["AlbCloudFront", "DomainName"]}
        },
        "CloudFrontUrl": {"Value": {"Fn::Sub": "https://${AlbCloudFront.DomainName}"}},
    },
}

CF_NO_CUSTOM_DOMAIN_ALBCLOUDFRONT = {
    "Properties": {
        "DistributionConfig": {
            "Enabled": True,
            "PriceClass": "PriceClass_100",
            "Origins": [
                {
                    "DomainName": {
                        "Fn::If": [
                            "UseDedicatedAlb",
                            {"Fn::GetAtt": ["DedicatedAlb", "DNSName"]},
                            {"Ref": "SharedAlbDnsName"},
                        ]
                    },
                    "Id": "AlbOrigin",
                    "CustomOriginConfig": {
                        "HTTPPort": 80,
                        "HTTPSPort": 443,
                        "OriginProtocolPolicy": "https-only",
                    },
                }
            ],
            "DefaultCacheBehavior": {
                "TargetOriginId": "AlbOrigin",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": [
                    "GET",
                    "HEAD",
                    "OPTIONS",
                    "PUT",
                    "PATCH",
                    "POST",
                    "DELETE",
                ],
                "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                "Compress": True,
                "MinTTL": 0,
                "DefaultTTL": 0,
                "MaxTTL": 0,
                "ForwardedValues": {
                    "QueryString": True,
                    "Cookies": {"Forward": "all"},
                    "Headers": ["*"],
                },
            },
            "CacheBehaviors": [
                {
                    "PathPattern": "/iiif/*",
                    "TargetOriginId": "AlbOrigin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": [
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "PATCH",
                        "POST",
                        "DELETE",
                    ],
                    "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                    "Compress": True,
                    "MinTTL": 0,
                    "DefaultTTL": 3600,
                    "MaxTTL": 31536000,
                    "ForwardedValues": {
                        "QueryString": True,
                        "Cookies": {"Forward": "none"},
                        "Headers": ["Host"],
                    },
                }
            ],
        },
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
    },
    "Type": "AWS::CloudFront::Distribution",
}

CF_DEDICATED_ALBCLOUDFRONT = {
    "Properties": {
        "DistributionConfig": {
            "Enabled": True,
            "PriceClass": "PriceClass_100",
            "Origins": [
                {
                    "DomainName": {
                        "Fn::If": [
                            "UseDedicatedAlb",
                            {"Fn::GetAtt": ["DedicatedAlb", "DNSName"]},
                            {"Ref": "SharedAlbDnsName"},
                        ]
                    },
                    "Id": "AlbOrigin",
                    "CustomOriginConfig": {
                        "HTTPPort": 80,
                        "HTTPSPort": 443,
                        "OriginProtocolPolicy": "https-only",
                    },
                }
            ],
            "DefaultCacheBehavior": {
                "TargetOriginId": "AlbOrigin",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": [
                    "GET",
                    "HEAD",
                    "OPTIONS",
                    "PUT",
                    "PATCH",
                    "POST",
                    "DELETE",
                ],
                "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                "Compress": True,
                "MinTTL": 0,
                "DefaultTTL": 0,
                "MaxTTL": 0,
                "ForwardedValues": {
                    "QueryString": True,
                    "Cookies": {"Forward": "all"},
                    "Headers": ["*"],
                },
            },
            "Aliases": ["cdn.example.com"],
            "ViewerCertificate": {
                "AcmCertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555",
                "SslSupportMethod": "sni-only",
                "MinimumProtocolVersion": "TLSv1.2_2021",
            },
            "CacheBehaviors": [
                {
                    "PathPattern": "/iiif/*",
                    "TargetOriginId": "AlbOrigin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": [
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "PATCH",
                        "POST",
                        "DELETE",
                    ],
                    "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                    "Compress": True,
                    "MinTTL": 0,
                    "DefaultTTL": 3600,
                    "MaxTTL": 31536000,
                    "ForwardedValues": {
                        "QueryString": True,
                        "Cookies": {"Forward": "none"},
                        "Headers": ["Host"],
                    },
                }
            ],
        },
        "Tags": [
            {"Key": "Project", "Value": {"Ref": "ProjectName"}},
            {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
            {
                "Fn::If": [
                    "HasExtraTagEnvironmentType",
                    {
                        "Key": "environment-type",
                        "Value": {"Ref": "ExtraTagEnvironmentType"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagEphemeralCleanupId",
                    {
                        "Key": "ephemeral-cleanup-id",
                        "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPreviewBaseEnvironment",
                    {
                        "Key": "preview-base-environment",
                        "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                    },
                    {"Ref": "AWS::NoValue"},
                ]
            },
            {
                "Fn::If": [
                    "HasExtraTagPullRequest",
                    {"Key": "pull-request", "Value": {"Ref": "ExtraTagPullRequest"}},
                    {"Ref": "AWS::NoValue"},
                ]
            },
        ],
    },
    "Type": "AWS::CloudFront::Distribution",
}

FULL_FEATURED_RESOURCES = {
    "AlbCloudFront": {
        "Properties": {
            "DistributionConfig": {
                "Enabled": True,
                "PriceClass": "PriceClass_100",
                "Origins": [
                    {
                        "DomainName": {
                            "Fn::If": [
                                "UseDedicatedAlb",
                                {"Fn::GetAtt": ["DedicatedAlb", "DNSName"]},
                                {"Ref": "SharedAlbDnsName"},
                            ]
                        },
                        "Id": "AlbOrigin",
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "HTTPSPort": 443,
                            "OriginProtocolPolicy": "https-only",
                        },
                    }
                ],
                "DefaultCacheBehavior": {
                    "TargetOriginId": "AlbOrigin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": [
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "PATCH",
                        "POST",
                        "DELETE",
                    ],
                    "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                    "Compress": True,
                    "MinTTL": 0,
                    "DefaultTTL": 0,
                    "MaxTTL": 0,
                    "ForwardedValues": {
                        "QueryString": True,
                        "Cookies": {"Forward": "all"},
                        "Headers": ["*"],
                    },
                },
                "Comment": "demo cdn",
                "Aliases": ["cdn.example.com"],
                "ViewerCertificate": {
                    "AcmCertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555",
                    "SslSupportMethod": "sni-only",
                    "MinimumProtocolVersion": "TLSv1.2_2021",
                },
                "CacheBehaviors": [
                    {
                        "PathPattern": "/iiif/*",
                        "TargetOriginId": "AlbOrigin",
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": [
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "PUT",
                            "PATCH",
                            "POST",
                            "DELETE",
                        ],
                        "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                        "Compress": False,
                        "MinTTL": 0,
                        "DefaultTTL": 3600,
                        "MaxTTL": 31536000,
                        "ForwardedValues": {
                            "QueryString": True,
                            "QueryStringCacheKeys": ["v", "page"],
                            "Cookies": {
                                "Forward": "whitelist",
                                "WhitelistedNames": ["session"],
                            },
                            "Headers": ["Host", "Authorization"],
                        },
                    },
                    {
                        "PathPattern": "/assets/*",
                        "TargetOriginId": "AlbOrigin",
                        "ViewerProtocolPolicy": "redirect-to-https",
                        "AllowedMethods": [
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "PUT",
                            "PATCH",
                            "POST",
                            "DELETE",
                        ],
                        "CachedMethods": ["GET", "HEAD", "OPTIONS"],
                        "Compress": True,
                        "MinTTL": 0,
                        "DefaultTTL": 3600,
                        "MaxTTL": 31536000,
                        "ForwardedValues": {
                            "QueryString": True,
                            "Cookies": {"Forward": "none"},
                            "Headers": ["Host"],
                        },
                    },
                ],
            },
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::CloudFront::Distribution",
    },
    "CloudFrontOacmediafiles": {
        "Properties": {
            "OriginAccessControlConfig": {
                "Name": {
                    "Fn::Sub": "${ProjectName}-${EnvironmentName}-media-files-oac"
                },
                "OriginAccessControlOriginType": "s3",
                "SigningBehavior": "always",
                "SigningProtocol": "sigv4",
            }
        },
        "Type": "AWS::CloudFront::OriginAccessControl",
    },
    "CloudFrontmediafiles": {
        "Properties": {
            "DistributionConfig": {
                "Enabled": True,
                "Origins": [
                    {
                        "DomainName": {
                            "Fn::GetAtt": ["Bucketmediafiles", "RegionalDomainName"]
                        },
                        "Id": "S3mediafilesOrigin",
                        "S3OriginConfig": {},
                        "OriginAccessControlId": {
                            "Fn::GetAtt": ["CloudFrontOacmediafiles", "Id"]
                        },
                    }
                ],
                "DefaultCacheBehavior": {
                    "TargetOriginId": "S3mediafilesOrigin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": ["GET", "HEAD", "OPTIONS"],
                    "CachedMethods": ["GET", "HEAD"],
                    "Compress": True,
                    "ForwardedValues": {
                        "QueryString": False,
                        "Cookies": {"Forward": "none"},
                    },
                },
                "PriceClass": "PriceClass_100",
            },
            "Tags": [
                {"Key": "Project", "Value": {"Ref": "ProjectName"}},
                {"Key": "Environment", "Value": {"Ref": "EnvironmentName"}},
                {
                    "Fn::If": [
                        "HasExtraTagEnvironmentType",
                        {
                            "Key": "environment-type",
                            "Value": {"Ref": "ExtraTagEnvironmentType"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagEphemeralCleanupId",
                        {
                            "Key": "ephemeral-cleanup-id",
                            "Value": {"Ref": "ExtraTagEphemeralCleanupId"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPreviewBaseEnvironment",
                        {
                            "Key": "preview-base-environment",
                            "Value": {"Ref": "ExtraTagPreviewBaseEnvironment"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
                {
                    "Fn::If": [
                        "HasExtraTagPullRequest",
                        {
                            "Key": "pull-request",
                            "Value": {"Ref": "ExtraTagPullRequest"},
                        },
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            ],
        },
        "Type": "AWS::CloudFront::Distribution",
    },
    "BucketPolicymediafiles": {
        "Properties": {
            "Bucket": {"Ref": "Bucketmediafiles"},
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowCloudFrontRead",
                        "Effect": "Allow",
                        "Principal": {"Service": "cloudfront.amazonaws.com"},
                        "Action": "s3:GetObject",
                        "Resource": {"Fn::Sub": "${Bucketmediafiles.Arn}/*"},
                        "Condition": {
                            "StringEquals": {
                                "AWS:SourceArn": {
                                    "Fn::Sub": "arn:aws:cloudfront::${AWS::AccountId}:distribution/${CloudFrontmediafiles}"
                                }
                            }
                        },
                    }
                ],
            },
        },
        "Type": "AWS::S3::BucketPolicy",
    },
}

FULL_FEATURED_SERVICE_PARAMETERS = {
    "ProjectName": {"Ref": "ProjectName"},
    "EnvironmentName": {"Ref": "EnvironmentName"},
    "VpcId": {"Ref": "VpcId"},
    "VpcCidr": {"Ref": "VpcCidr"},
    "PrivateSubnetIds": {"Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]},
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
    "ExtraTagEnvironmentType": {"Ref": "ExtraTagEnvironmentType"},
    "ExtraTagEphemeralCleanupId": {"Ref": "ExtraTagEphemeralCleanupId"},
    "ExtraTagPreviewBaseEnvironment": {"Ref": "ExtraTagPreviewBaseEnvironment"},
    "ExtraTagPullRequest": {"Ref": "ExtraTagPullRequest"},
    "DefaultListenerPriority": {"Ref": "DefaultListenerPriority"},
    "BucketNameMediaFiles": {"Ref": "Bucketmediafiles"},
    "BucketArnMediaFiles": {"Fn::GetAtt": ["Bucketmediafiles", "Arn"]},
    "CloudFrontUrlMediaFiles": {
        "Fn::Sub": "https://${CloudFrontmediafiles.DomainName}"
    },
    "CloudFrontUrlCDNURL": {"Fn::Sub": "https://${AlbCloudFront.DomainName}"},
}
