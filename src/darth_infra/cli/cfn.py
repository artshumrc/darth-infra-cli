"""CloudFormation deployment helpers and lookup resolvers."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..config.models import ProjectConfig
from .helpers import console


@dataclass
class ResolvedLookupData:
    vpc_id: str
    vpc_cidr: str
    private_subnet_ids: list[str]
    public_subnet_ids: list[str]
    shared_listener_arn: str
    shared_alb_security_group_id: str
    default_listener_priority: int | None
    path_rule_priorities: dict[str, int]
    rds_snapshot_identifier: str
    env_secret_arns: dict[str, str]


def resolve_lookup_data(config: ProjectConfig, env_name: str) -> ResolvedLookupData:
    ec2 = boto3.client("ec2", region_name=config.aws_region)
    elbv2 = boto3.client("elbv2", region_name=config.aws_region)

    vpc_id, vpc_cidr, private_subnets, public_subnets = _resolve_network(config, ec2)
    listener_arn, alb_sg = _resolve_shared_alb(config, elbv2)
    default_priority, path_priorities = _resolve_listener_priorities(
        config, elbv2, listener_arn
    )
    snapshot = _resolve_rds_snapshot(config, env_name)
    env_secrets = _resolve_env_secrets(config)

    return ResolvedLookupData(
        vpc_id=vpc_id,
        vpc_cidr=vpc_cidr,
        private_subnet_ids=private_subnets,
        public_subnet_ids=public_subnets,
        shared_listener_arn=listener_arn,
        shared_alb_security_group_id=alb_sg,
        default_listener_priority=default_priority,
        path_rule_priorities=path_priorities,
        rds_snapshot_identifier=snapshot,
        env_secret_arns=env_secrets,
    )


def ensure_artifact_bucket(config: ProjectConfig) -> str:
    sts = boto3.client("sts")
    account = sts.get_caller_identity()["Account"]
    bucket_name = f"darth-infra-artifacts-{account}-{config.aws_region}".lower()
    s3 = boto3.client("s3", region_name=config.aws_region)

    try:
        s3.head_bucket(Bucket=bucket_name)
        return bucket_name
    except ClientError:
        pass

    kwargs: dict[str, object] = {"Bucket": bucket_name}
    if config.aws_region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {
            "LocationConstraint": config.aws_region,
        }
    s3.create_bucket(**kwargs)
    return bucket_name


def package_template(project_dir: Path, config: ProjectConfig, env_name: str, bucket: str) -> Path:
    build_dir = project_dir / ".darth-infra" / "build" / env_name
    build_dir.mkdir(parents=True, exist_ok=True)

    template_file = project_dir / "templates" / "generated" / "root.yaml"
    if not template_file.is_file():
        raise FileNotFoundError(
            f"Missing template file: {template_file}. Run 'darth-infra init' first."
        )

    output_template = build_dir / "packaged-root.yaml"
    cmd = [
        "aws",
        "cloudformation",
        "package",
        "--region",
        config.aws_region,
        "--template-file",
        str(template_file),
        "--s3-bucket",
        bucket,
        "--output-template-file",
        str(output_template),
    ]

    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, cwd=str(project_dir))
    if result.returncode != 0:
        raise RuntimeError("cloudformation package failed")

    return output_template


def deploy_changeset(
    config: ProjectConfig,
    env_name: str,
    template_path: Path,
    lookups: ResolvedLookupData,
    *,
    no_execute: bool,
    changeset_name: str | None,
) -> int:
    cf = boto3.client("cloudformation", region_name=config.aws_region)
    stack_name = f"{config.project_name}-ecs-{env_name}"

    template_body = template_path.read_text()
    parameters = _build_parameters(config, env_name, lookups)

    change_set_type = "UPDATE"
    existing_status: str | None = None
    try:
        stack = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
        existing_status = stack.get("StackStatus")
    except ClientError:
        change_set_type = "CREATE"

    if existing_status == "ROLLBACK_COMPLETE":
        console.print(
            f"[red]Stack '{stack_name}' is in ROLLBACK_COMPLETE and cannot be updated.[/red]"
        )
        console.print(
            f"[yellow]Delete it first, then redeploy:[/yellow]\n"
            f"  aws cloudformation delete-stack --region {config.aws_region} --stack-name {stack_name}\n"
            f"  aws cloudformation wait stack-delete-complete --region {config.aws_region} --stack-name {stack_name}"
        )
        return 1

    cs_name = changeset_name or f"darth-{env_name}-{int(time.time())}"

    resp = cf.create_change_set(
        StackName=stack_name,
        ChangeSetName=cs_name,
        ChangeSetType=change_set_type,
        Description=f"darth-infra deploy {env_name}",
        TemplateBody=template_body,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=parameters,
        Tags=[
            {"Key": "project", "Value": config.project_name},
            {"Key": "environment", "Value": env_name},
            {"Key": "managed-by", "Value": "darth-infra"},
            {"Key": "deployment-type", "Value": "ecs"},
            *[{"Key": k, "Value": v} for k, v in config.tags.items()],
        ],
    )
    cs_arn = resp["Id"]

    status, reason, changes = _wait_for_changeset(cf, cs_arn)
    if status == "FAILED":
        if "didn't contain changes" in reason.lower():
            console.print("[green]No infrastructure changes detected.[/green]")
            return 0
        console.print(f"[red]Change set failed: {reason}[/red]")
        return 1

    console.print(f"[bold]Change set:[/bold] [cyan]{cs_name}[/cyan]")
    if changes:
        for c in changes:
            rc = c.get("ResourceChange", {})
            console.print(
                f"- {rc.get('Action', '?')}: {rc.get('LogicalResourceId', '?')} ({rc.get('ResourceType', '?')})"
            )
    else:
        console.print("- (no detailed resource changes returned)")

    if no_execute:
        console.print("[yellow]Change set created but not executed (--no-execute).[/yellow]")
        return 0

    cf.execute_change_set(ChangeSetName=cs_arn, StackName=stack_name)
    console.print("[bold]Executing change set...[/bold]")

    waiter_name = "stack_create_complete" if change_set_type == "CREATE" else "stack_update_complete"
    waiter = cf.get_waiter(waiter_name)
    try:
        waiter.wait(StackName=stack_name)
    except Exception as exc:
        console.print(f"[red]Stack operation failed: {exc}[/red]")
        _print_stack_failure_details(cf, stack_name)
        return 1

    return 0


def delete_stack(config: ProjectConfig, env_name: str) -> int:
    cf = boto3.client("cloudformation", region_name=config.aws_region)
    stack_name = f"{config.project_name}-ecs-{env_name}"
    try:
        cf.delete_stack(StackName=stack_name)
        waiter = cf.get_waiter("stack_delete_complete")
        waiter.wait(StackName=stack_name)
        return 0
    except ClientError as exc:
        console.print(f"[red]Delete failed: {exc}[/red]")
        return 1


def _wait_for_changeset(cf, cs_arn: str) -> tuple[str, str, list[dict]]:
    while True:
        desc = cf.describe_change_set(ChangeSetName=cs_arn)
        status = desc.get("Status", "")
        reason = desc.get("StatusReason", "")
        if status in {"CREATE_COMPLETE", "FAILED"}:
            return status, reason, desc.get("Changes", [])
        time.sleep(2)


def _print_stack_failure_details(cf, stack_name: str) -> None:
    try:
        stack_desc = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as exc:
        console.print(f"[red]Could not load stack details for '{stack_name}': {exc}[/red]")
        return

    stack_status = stack_desc.get("StackStatus", "UNKNOWN")
    status_reason = stack_desc.get("StackStatusReason", "")
    if status_reason:
        console.print(
            f"[red]Stack status:[/red] [bold]{stack_status}[/bold] - {status_reason}"
        )
    else:
        console.print(f"[red]Stack status:[/red] [bold]{stack_status}[/bold]")

    _print_failed_events(cf, stack_name, label=f"Root stack ({stack_name})")

    nested_stack_ids = _collect_failed_nested_stack_ids(cf, stack_name)
    for nested_stack_id in nested_stack_ids[:3]:
        _print_failed_events(cf, nested_stack_id, label=f"Nested stack ({nested_stack_id})")


def _collect_failed_nested_stack_ids(cf, stack_name: str) -> list[str]:
    try:
        events = cf.describe_stack_events(StackName=stack_name).get("StackEvents", [])
    except ClientError:
        return []

    nested_ids: list[str] = []
    for event in events:
        if event.get("ResourceType") != "AWS::CloudFormation::Stack":
            continue
        if not str(event.get("ResourceStatus", "")).endswith("FAILED"):
            continue
        nested_id = event.get("PhysicalResourceId")
        if nested_id and nested_id not in nested_ids:
            nested_ids.append(nested_id)
    return nested_ids


def _print_failed_events(cf, stack_name: str, *, label: str) -> None:
    try:
        events = cf.describe_stack_events(StackName=stack_name).get("StackEvents", [])
    except ClientError as exc:
        console.print(f"[yellow]Could not load events for {label}: {exc}[/yellow]")
        return

    failed_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        status = str(event.get("ResourceStatus", ""))
        if not status.endswith("FAILED"):
            continue

        logical_id = event.get("LogicalResourceId", "?")
        resource_type = event.get("ResourceType", "?")
        reason = event.get("ResourceStatusReason", "(no reason provided)")
        key = (logical_id, status, reason)
        if key in seen:
            continue
        seen.add(key)
        failed_events.append(
            {
                "logical_id": logical_id,
                "resource_type": resource_type,
                "status": status,
                "reason": reason,
            }
        )
        if len(failed_events) >= 5:
            break

    if not failed_events:
        return

    console.print(f"[bold red]Failed events in {label}:[/bold red]")
    for event in failed_events:
        console.print(
            f"- {event['logical_id']} ({event['resource_type']}) [{event['status']}] - {event['reason']}"
        )


def _resolve_network(config: ProjectConfig, ec2) -> tuple[str, str, list[str], list[str]]:
    vpc_id = config.vpc_id
    vpc_cidr = ""
    if not vpc_id:
        resp = ec2.describe_vpcs(
            Filters=[
                {"Name": "tag:Name", "Values": [config.vpc_name]},
            ]
        )
        vpcs = resp.get("Vpcs", [])
        if len(vpcs) != 1:
            raise RuntimeError(
                f"Expected exactly one VPC with Name={config.vpc_name}, found {len(vpcs)}"
            )
        vpc_id = vpcs[0]["VpcId"]
        vpc_cidr = str(vpcs[0].get("CidrBlock", ""))
    else:
        vpcs = ec2.describe_vpcs(VpcIds=[vpc_id]).get("Vpcs", [])
        if len(vpcs) != 1:
            raise RuntimeError(f"Could not resolve VPC CIDR for vpc_id={vpc_id}")
        vpc_cidr = str(vpcs[0].get("CidrBlock", ""))

    private_subnets = list(config.private_subnet_ids)
    public_subnets = list(config.public_subnet_ids)

    if not private_subnets or not public_subnets:
        subnets = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("Subnets", [])

        if not private_subnets:
            private_subnets = [
                s["SubnetId"]
                for s in subnets
                if not s.get("MapPublicIpOnLaunch", False)
            ]
        if not public_subnets:
            public_subnets = [
                s["SubnetId"] for s in subnets if s.get("MapPublicIpOnLaunch", False)
            ]

    if not private_subnets:
        raise RuntimeError("Could not resolve private subnets")
    if len(private_subnets) > 16:
        raise RuntimeError(
            "Resolved "
            f"{len(private_subnets)} private subnets for VPC {vpc_id}, but ECS services "
            "support at most 16 subnets in awsvpc mode. Set project.private_subnet_ids "
            "in darth-infra.toml to a smaller explicit list (typically 2-6 subnets "
            "across availability zones)."
        )
    if config.alb.mode.value == "dedicated" and not public_subnets:
        raise RuntimeError("Could not resolve public subnets required for dedicated ALB")

    if not vpc_cidr:
        raise RuntimeError(f"Could not resolve CIDR block for VPC {vpc_id}")

    return vpc_id, vpc_cidr, private_subnets, public_subnets


def _resolve_shared_alb(config: ProjectConfig, elbv2) -> tuple[str, str]:
    if config.alb.mode.value != "shared":
        return "", ""

    listener_arn = config.alb.shared_listener_arn
    alb_sg = config.alb.shared_alb_security_group_id
    if listener_arn and alb_sg:
        return listener_arn, alb_sg

    if not config.alb.shared_alb_name:
        raise RuntimeError("alb.shared_alb_name is required in shared mode")

    lbs = elbv2.describe_load_balancers(Names=[config.alb.shared_alb_name]).get(
        "LoadBalancers", []
    )
    if len(lbs) != 1:
        raise RuntimeError(
            f"Expected one ALB named {config.alb.shared_alb_name}, found {len(lbs)}"
        )
    alb = lbs[0]
    alb_sg = alb["SecurityGroups"][0]

    listeners = elbv2.describe_listeners(LoadBalancerArn=alb["LoadBalancerArn"]).get(
        "Listeners", []
    )
    preferred = next(
        (l for l in listeners if l.get("Protocol") == "HTTPS" and l.get("Port") == 443),
        None,
    )
    if not preferred:
        preferred = next((l for l in listeners if l.get("Port") in {80, 443}), None)
    if not preferred:
        raise RuntimeError("Could not find an ALB listener to attach rules")

    return preferred["ListenerArn"], alb_sg


def _resolve_listener_priorities(
    config: ProjectConfig,
    elbv2,
    listener_arn: str,
) -> tuple[int | None, dict[str, int]]:
    if not config.alb.domain:
        return None, {}

    if config.alb.default_listener_priority is None:
        raise RuntimeError(
            "alb.default_listener_priority is required when alb.domain is configured"
        )
    desired_priorities = {
        "default": config.alb.default_listener_priority,
        **{rule.name: rule.priority for rule in config.alb.path_rules},
    }

    if config.alb.mode.value != "shared":
        return config.alb.default_listener_priority, {
            rule.name: rule.priority for rule in config.alb.path_rules
        }

    existing: set[int] = set()
    paginator = elbv2.get_paginator("describe_rules")
    for page in paginator.paginate(ListenerArn=listener_arn):
        for rule in page.get("Rules", []):
            p = rule.get("Priority")
            if p and p != "default":
                try:
                    existing.add(int(p))
                except ValueError:
                    continue

    conflicts = sorted(
        priority
        for priority in desired_priorities.values()
        if priority in existing
    )
    if conflicts:
        raise RuntimeError(
            "ALB listener rule priorities already in use on shared listener: "
            f"{', '.join(str(p) for p in conflicts)}. "
            "Choose different priorities (use the TUI 'Get next available priority' button)."
        )

    return config.alb.default_listener_priority, {
        rule.name: rule.priority for rule in config.alb.path_rules
    }


def _resolve_rds_snapshot(config: ProjectConfig, env_name: str) -> str:
    if not config.rds or env_name == "prod":
        return ""

    rds = boto3.client("rds", region_name=config.aws_region)
    db_id = f"{config.project_name}-prod-db"
    try:
        snapshots = rds.describe_db_snapshots(
            DBInstanceIdentifier=db_id,
            SnapshotType="automated",
        ).get("DBSnapshots", [])
    except Exception:
        return ""

    if not snapshots:
        return ""
    latest = max(snapshots, key=lambda s: s.get("SnapshotCreateTime"))
    return latest["DBSnapshotIdentifier"]


def _resolve_env_secrets(config: ProjectConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    sm = boto3.client("secretsmanager", region_name=config.aws_region)
    for sec in config.secrets:
        if sec.source.value != "env":
            continue
        value = os.getenv(sec.name, "").strip()
        if not value:
            raise RuntimeError(
                f"Secret '{sec.name}' source is 'env' but environment variable is not set"
            )
        if value.startswith("arn:"):
            out[sec.name] = value
            continue
        info = sm.describe_secret(SecretId=value)
        out[sec.name] = info["ARN"]
    return out


def _build_parameters(
    config: ProjectConfig,
    env_name: str,
    lookups: ResolvedLookupData,
) -> list[dict[str, str]]:
    params = [
        {"ParameterKey": "ProjectName", "ParameterValue": config.project_name},
        {"ParameterKey": "EnvironmentName", "ParameterValue": env_name},
        {"ParameterKey": "VpcId", "ParameterValue": lookups.vpc_id},
        {"ParameterKey": "VpcCidr", "ParameterValue": lookups.vpc_cidr},
        {
            "ParameterKey": "PrivateSubnetIds",
            "ParameterValue": ",".join(lookups.private_subnet_ids),
        },
        {
            "ParameterKey": "PublicSubnetIds",
            "ParameterValue": ",".join(lookups.public_subnet_ids),
        },
        {"ParameterKey": "AlbMode", "ParameterValue": config.alb.mode.value},
        {
            "ParameterKey": "SharedAlbListenerArn",
            "ParameterValue": lookups.shared_listener_arn,
        },
        {
            "ParameterKey": "SharedAlbSecurityGroupId",
            "ParameterValue": lookups.shared_alb_security_group_id,
        },
        {
            "ParameterKey": "CertificateArn",
            "ParameterValue": config.alb.certificate_arn or "",
        },
    ]
    cluster_domain = config.get_cluster_domain(env_name)
    params.append(
        {
            "ParameterKey": "ClusterDomain",
            "ParameterValue": cluster_domain or "",
        }
    )

    if config.rds:
        env_override = config.environment_overrides.get(env_name)
        rds_type = config.rds.instance_type
        if env_override and env_override.instance_type_override:
            rds_type = env_override.instance_type_override
        params.extend(
            [
                {
                    "ParameterKey": "RdsSnapshotIdentifier",
                    "ParameterValue": lookups.rds_snapshot_identifier,
                },
                {"ParameterKey": "RdsInstanceType", "ParameterValue": rds_type},
            ]
        )

    for sec in config.secrets:
        if sec.source.value != "env":
            continue
        key = f"EnvSecretArn{sec.name.replace('_', '').replace('-', '')}"
        params.append(
            {
                "ParameterKey": key,
                "ParameterValue": lookups.env_secret_arns.get(sec.name, ""),
            }
        )

    return params
