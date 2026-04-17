"""CloudFormation deployment helpers and lookup resolvers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..config.models import ProjectConfig
from .helpers import console, get_cluster_name, get_service_name


@dataclass
class ResolvedLookupData:
    vpc_id: str
    vpc_cidr: str
    private_subnet_ids: list[str]
    public_subnet_ids: list[str]
    shared_listener_arn: str
    shared_alb_security_group_id: str
    shared_alb_dns_name: str
    default_listener_priority: int | None
    path_rule_priorities: dict[str, int]
    rds_snapshot_identifier: str
    external_secret_arns: dict[str, str]
    existing_service_discovery_namespace_id: str


@dataclass
class DeployMonitorState:
    seen_stack_event_ids: set[str]
    seen_service_event_keys: set[str]
    seen_task_failure_keys: set[str]
    log_since_ms_by_service: dict[str, int]
    last_pending_signature: str
    fatal_ecs_messages: list[str]


def resolve_lookup_data(config: ProjectConfig, env_name: str) -> ResolvedLookupData:
    ec2 = boto3.client("ec2", region_name=config.aws_region)
    elbv2 = boto3.client("elbv2", region_name=config.aws_region)
    sd = boto3.client("servicediscovery", region_name=config.aws_region)
    route53 = boto3.client("route53")

    vpc_id, vpc_cidr, private_subnets, public_subnets = _resolve_network(config, ec2)
    listener_arn, alb_sg, alb_dns_name = _resolve_shared_alb(config, elbv2)
    default_priority, path_priorities = _resolve_listener_priorities(
        config, env_name, elbv2, listener_arn
    )
    snapshot = _resolve_rds_snapshot(config, env_name)
    external_secrets = _resolve_external_secrets(config)
    namespace_id = _resolve_existing_service_discovery_namespace(
        config, sd, route53, vpc_id
    )

    resolved = ResolvedLookupData(
        vpc_id=vpc_id,
        vpc_cidr=vpc_cidr,
        private_subnet_ids=private_subnets,
        public_subnet_ids=public_subnets,
        shared_listener_arn=listener_arn,
        shared_alb_security_group_id=alb_sg,
        shared_alb_dns_name=alb_dns_name,
        default_listener_priority=default_priority,
        path_rule_priorities=path_priorities,
        rds_snapshot_identifier=snapshot,
        external_secret_arns=external_secrets,
        existing_service_discovery_namespace_id=namespace_id,
    )

    _validate_resolved_lookup_data(config, resolved, ec2, elbv2)
    return resolved


def _validate_resolved_lookup_data(
    config: ProjectConfig,
    lookups: ResolvedLookupData,
    ec2,
    elbv2,
) -> None:
    try:
        ec2.describe_vpcs(VpcIds=[lookups.vpc_id])
    except ClientError as exc:
        raise RuntimeError(
            f"Resolved VPC '{lookups.vpc_id}' does not exist or is not accessible in {config.aws_region}"
        ) from exc

    _validate_subnet_ids(
        ec2,
        subnet_ids=lookups.private_subnet_ids,
        vpc_id=lookups.vpc_id,
        label="private_subnet_ids",
    )
    _validate_subnet_ids(
        ec2,
        subnet_ids=lookups.public_subnet_ids,
        vpc_id=lookups.vpc_id,
        label="public_subnet_ids",
    )

    if config.alb.mode.value != "shared":
        return

    listener_arn = lookups.shared_listener_arn
    sg_id = lookups.shared_alb_security_group_id
    if not listener_arn:
        raise RuntimeError(
            "Shared ALB mode requires a listener ARN, but none was resolved"
        )
    if not sg_id:
        raise RuntimeError(
            "Shared ALB mode requires an ALB security group ID, but none was resolved"
        )

    try:
        listener_resp = elbv2.describe_listeners(ListenerArns=[listener_arn])
        listeners = listener_resp.get("Listeners", [])
    except ClientError as exc:
        raise RuntimeError(
            f"Shared ALB listener ARN '{listener_arn}' does not exist or is not accessible"
        ) from exc

    if len(listeners) != 1:
        raise RuntimeError(
            f"Expected one listener for ARN '{listener_arn}', found {len(listeners)}"
        )
    listener_protocol = str(listeners[0].get("Protocol", "")).strip().upper()
    listener_port = listeners[0].get("Port")
    if config.cloudfront.enabled and config.cloudfront.origin_https_only:
        if listener_protocol != "HTTPS" or listener_port != 443:
            raise RuntimeError(
                "cloudfront.origin_https_only requires shared ALB listener HTTPS:443, "
                f"but resolved listener is {listener_protocol or 'unknown'}:{listener_port}"
            )

    load_balancer_arn = str(listeners[0].get("LoadBalancerArn", "")).strip()
    if not load_balancer_arn:
        raise RuntimeError(
            f"Could not determine load balancer ARN for listener '{listener_arn}'"
        )

    try:
        sg_resp = ec2.describe_security_groups(GroupIds=[sg_id])
        groups = sg_resp.get("SecurityGroups", [])
    except ClientError as exc:
        raise RuntimeError(
            f"Shared ALB security group '{sg_id}' does not exist or is not accessible"
        ) from exc

    if len(groups) != 1:
        raise RuntimeError(
            f"Expected one security group for '{sg_id}', found {len(groups)}"
        )

    sg_vpc_id = str(groups[0].get("VpcId", "")).strip()
    if sg_vpc_id and sg_vpc_id != lookups.vpc_id:
        raise RuntimeError(
            f"Shared ALB security group '{sg_id}' is in VPC '{sg_vpc_id}', expected '{lookups.vpc_id}'"
        )

    try:
        lb_resp = elbv2.describe_load_balancers(LoadBalancerArns=[load_balancer_arn])
        lbs = lb_resp.get("LoadBalancers", [])
    except ClientError as exc:
        raise RuntimeError(
            f"Shared ALB '{load_balancer_arn}' for listener '{listener_arn}' is not accessible"
        ) from exc

    if len(lbs) != 1:
        raise RuntimeError(
            f"Expected one load balancer for ARN '{load_balancer_arn}', found {len(lbs)}"
        )

    lb_security_groups = set(lbs[0].get("SecurityGroups", []))
    if sg_id not in lb_security_groups:
        raise RuntimeError(
            f"Shared ALB security group '{sg_id}' is not attached to load balancer '{load_balancer_arn}'"
        )
    if config.cloudfront.enabled and not lookups.shared_alb_dns_name:
        raise RuntimeError(
            "CloudFront is enabled but shared ALB DNS name could not be resolved"
        )


def validate_rendered_deploy_templates(
    project_dir: Path,
    config: ProjectConfig,
    env_name: str,
    lookups: ResolvedLookupData,
) -> None:
    root_template = project_dir / "templates" / "generated" / "root.yaml"
    if not root_template.is_file():
        raise FileNotFoundError(f"Missing template file: {root_template}")

    root_body = root_template.read_text()
    service_dir = project_dir / "templates" / "generated" / "services"
    secrets_by_name = {sec.name: sec for sec in config.secrets}
    rds_key_by_env = {
        "DATABASE_HOST": "host",
        "DATABASE_PORT": "port",
        "DATABASE_DB": "dbname",
        "DATABASE_USER": "username",
        "DATABASE_PASSWORD": "password",
        "POSTGRES_HOST": "host",
        "POSTGRES_PORT": "port",
        "POSTGRES_DB": "dbname",
        "POSTGRES_USER": "username",
        "POSTGRES_PASSWORD": "password",
    }

    for service in config.services:
        service_template = service_dir / f"{service.name}.yaml"
        if not service_template.is_file():
            raise FileNotFoundError(f"Missing service template file: {service_template}")
        service_body = service_template.read_text()

        if service.enable_ses_send_email:
            for required_marker in (
                "PolicyName: SesSendEmail",
                "- ses:SendEmail",
                "- ses:SendRawEmail",
                "- ses:GetSendQuota",
            ):
                if required_marker not in service_body:
                    raise RuntimeError(
                        f"Preflight validation failed for service '{service.name}': "
                        "SES task-role policy is missing required permissions"
                    )

        expected_secret_names = list(service.secrets)
        if config.rds and service.name in config.rds.expose_to:
            for secret_name in (
                "POSTGRES_DB",
                "POSTGRES_USER",
                "POSTGRES_PASSWORD",
                "POSTGRES_HOST",
                "POSTGRES_PORT",
            ):
                if secret_name not in expected_secret_names:
                    expected_secret_names.append(secret_name)

        expected_sources = set()
        for secret_name in expected_secret_names:
            secret_cfg = secrets_by_name.get(secret_name)
            source = getattr(getattr(secret_cfg, "source", None), "value", None)
            if source is None:
                if (
                    config.rds
                    and service.name in config.rds.expose_to
                    and secret_name in rds_key_by_env
                ):
                    source = "rds"
                else:
                    source = "generate"

            if source == "rds":
                expected_sources.add("RdsSecretArn")
                json_key = rds_key_by_env.get(
                    secret_name,
                    str(secret_cfg.existing_secret_name).strip() if secret_cfg else "",
                )
                expected_value = f"ValueFrom: !Sub '${{RdsSecretArn}}:{json_key}::'"
                if expected_value not in service_body:
                    raise RuntimeError(
                        f"Preflight validation failed for service '{service.name}': "
                        f"secret '{secret_name}' is missing the expected RDS ValueFrom mapping"
                    )
                if f"- Name: {secret_name}" not in service_body:
                    raise RuntimeError(
                        f"Preflight validation failed for service '{service.name}': "
                        f"secret '{secret_name}' is missing from the ECS task definition"
                    )
                continue

            param_name = f"SecretArn{_secret_logical_suffix(secret_name)}"
            if f"- Name: {secret_name}" not in service_body:
                raise RuntimeError(
                    f"Preflight validation failed for service '{service.name}': "
                    f"secret '{secret_name}' is missing from the ECS task definition"
                )
            if f"ValueFrom: !Ref {param_name}" not in service_body:
                raise RuntimeError(
                    f"Preflight validation failed for service '{service.name}': "
                    f"secret '{secret_name}' is missing the expected task ValueFrom reference"
                )
            if f"- !Ref {param_name}" not in service_body:
                raise RuntimeError(
                    f"Preflight validation failed for service '{service.name}': "
                    f"secret '{secret_name}' is missing from the task execution role policy"
                )

            if source == "generate":
                expected_root_value = (
                    f"{param_name}: !GetAtt Secret{_secret_logical_suffix(secret_name)}.Arn"
                )
            else:
                expected_arn = lookups.external_secret_arns.get(secret_name, "").strip()
                if not expected_arn:
                    raise RuntimeError(
                        f"Preflight validation failed: external secret '{secret_name}' did not resolve to an ARN"
                    )
                expected_root_value = (
                    f"{param_name}: !Ref EnvSecretArn{_secret_logical_suffix(secret_name)}"
                )

            if expected_root_value not in root_body:
                raise RuntimeError(
                    f"Preflight validation failed for service '{service.name}': "
                    f"secret '{secret_name}' is missing from the root stack nested-service parameters"
                )

        for source_name in sorted(expected_sources):
            if f"- !Ref {source_name}" not in service_body:
                raise RuntimeError(
                    f"Preflight validation failed for service '{service.name}': "
                    f"required secret source '{source_name}' is missing from the task execution role policy"
                )

    if config.rds and "RdsSecretArn: !GetAtt RdsCredentialsSecret.Arn" not in root_body:
        raise RuntimeError(
            "Preflight validation failed: root stack is missing the nested RDS secret ARN wiring"
        )


def _validate_subnet_ids(
    ec2, *, subnet_ids: list[str], vpc_id: str, label: str
) -> None:
    if not subnet_ids:
        raise RuntimeError(f"No subnet IDs resolved for {label}")

    unique_subnet_ids = sorted({subnet_id for subnet_id in subnet_ids if subnet_id})
    try:
        response = ec2.describe_subnets(SubnetIds=unique_subnet_ids)
    except ClientError as exc:
        raise RuntimeError(
            f"One or more subnet IDs in {label} do not exist or are not accessible: {', '.join(unique_subnet_ids)}"
        ) from exc

    subnets = response.get("Subnets", [])
    found_ids = {str(subnet.get("SubnetId", "")).strip() for subnet in subnets}
    missing = sorted(
        subnet_id for subnet_id in unique_subnet_ids if subnet_id not in found_ids
    )
    if missing:
        raise RuntimeError(
            f"Subnet IDs in {label} were not found: {', '.join(missing)}"
        )

    wrong_vpc = sorted(
        str(subnet.get("SubnetId", "")).strip()
        for subnet in subnets
        if str(subnet.get("VpcId", "")).strip() != vpc_id
    )
    if wrong_vpc:
        raise RuntimeError(
            f"Subnet IDs in {label} are not in VPC '{vpc_id}': {', '.join(wrong_vpc)}"
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


def package_template(
    project_dir: Path, config: ProjectConfig, env_name: str, bucket: str
) -> Path:
    build_dir = project_dir / ".darth-infra" / "build" / env_name
    build_dir.mkdir(parents=True, exist_ok=True)

    template_file = project_dir / "templates" / "generated" / "root.yaml"
    if not template_file.is_file():
        raise FileNotFoundError(
            f"Missing template file: {template_file}. Run 'darth-infra tui' first."
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

    if change_set_type == "UPDATE":
        update_error = _validate_update_stack_named_resource_collisions(
            cf=cf,
            config=config,
            env_name=env_name,
            stack_name=stack_name,
        )
        if update_error:
            console.print(f"[red]{update_error}[/red]")
            return 1

    if change_set_type == "CREATE":
        _validate_create_stack_named_resource_collisions(config, env_name)

    cs_name = changeset_name or f"darth-{env_name}-{int(time.time())}"

    resp = cf.create_change_set(
        StackName=stack_name,
        ChangeSetName=cs_name,
        ChangeSetType=change_set_type,
        Description=f"darth-infra deploy {env_name}",
        TemplateBody=template_body,
        Capabilities=[
            "CAPABILITY_IAM",
            "CAPABILITY_NAMED_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ],
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
        _print_changeset_failure_diagnostics(cf, cs_arn, stack_name)
        if "resourceexistencecheck" in reason.lower():
            console.print(
                "[yellow]Early validation indicates one or more referenced AWS resources do not exist or are not accessible.[/yellow]"
            )
            console.print(
                "[yellow]Check IDs/ARNs for VPC, subnets, shared ALB listener/security group, and external secrets.[/yellow]"
            )
        _print_recent_stack_events(
            cf,
            stack_name,
            label=f"Stack events for {stack_name}",
            max_events=15,
        )
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
        console.print(
            "[yellow]Change set created but not executed (--no-execute).[/yellow]"
        )
        return 0

    cf.execute_change_set(ChangeSetName=cs_arn, StackName=stack_name)
    console.print("[bold]Executing change set...[/bold]")
    success = _monitor_stack_deploy(
        cf=cf,
        config=config,
        env_name=env_name,
        stack_name=stack_name,
        poll_interval_seconds=15,
    )
    if success:
        return 0

    _print_stack_failure_details(cf, stack_name)
    return 1


def _validate_create_stack_named_resource_collisions(
    config: ProjectConfig,
    env_name: str,
) -> None:
    collisions: list[str] = []

    ecr = boto3.client("ecr", region_name=config.aws_region)
    ecs = boto3.client("ecs", region_name=config.aws_region)
    sm = boto3.client("secretsmanager", region_name=config.aws_region)
    s3 = boto3.client("s3", region_name=config.aws_region)
    rds = boto3.client("rds", region_name=config.aws_region)

    cluster_name = get_cluster_name(config.project_name, env_name)
    try:
        cluster_resp = ecs.describe_clusters(clusters=[cluster_name])
        existing_clusters = cluster_resp.get("clusters", [])
        if existing_clusters and existing_clusters[0].get("status") != "INACTIVE":
            collisions.append(f"ECS cluster already exists: {cluster_name}")
    except Exception:
        pass

    for service in config.services:
        if service.image:
            continue
        repo_name = f"{config.project_name}/{env_name}/{service.name}"
        try:
            ecr.describe_repositories(repositoryNames=[repo_name])
            collisions.append(f"ECR repository already exists: {repo_name}")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code != "RepositoryNotFoundException":
                collisions.append(
                    f"Could not verify ECR repository '{repo_name}': {exc}"
                )

    for secret in config.secrets:
        if secret.source.value != "generate":
            continue
        secret_name = f"/darth-infra/{config.project_name}/{env_name}/{secret.name}"
        try:
            sm.describe_secret(SecretId=secret_name)
            collisions.append(f"Secrets Manager secret already exists: {secret_name}")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code != "ResourceNotFoundException":
                collisions.append(f"Could not verify secret '{secret_name}': {exc}")

    for bucket in config.s3_buckets:
        if bucket.mode.value == "existing":
            continue
        bucket_name = f"{config.project_name}-{env_name}-{bucket.name}".lower()
        try:
            s3.head_bucket(Bucket=bucket_name)
            collisions.append(
                f"S3 bucket name is already in use or accessible: {bucket_name}"
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                continue
            if code in {"403", "Forbidden"}:
                collisions.append(
                    f"S3 bucket name is already owned by another account or inaccessible: {bucket_name}"
                )

    if config.rds:
        db_identifier = f"{config.project_name}-{env_name}-db"
        try:
            rds.describe_db_instances(DBInstanceIdentifier=db_identifier)
            collisions.append(
                f"RDS instance identifier already exists: {db_identifier}"
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code != "DBInstanceNotFound":
                collisions.append(
                    f"Could not verify RDS instance '{db_identifier}': {exc}"
                )

    if collisions:
        details = "\n  - " + "\n  - ".join(collisions)
        raise RuntimeError(
            "Preflight detected existing resources that conflict with initial stack creation:"
            f"{details}\n"
            "Resolve or rename these resources, or import/reuse them through config before deploying."
        )


def _validate_update_stack_named_resource_collisions(
    *,
    cf,
    config: ProjectConfig,
    env_name: str,
    stack_name: str,
) -> str | None:
    managed_logical_ids = _stack_logical_resource_ids(cf, stack_name)
    collisions: list[str] = []

    ecr = boto3.client("ecr", region_name=config.aws_region)
    ecs = boto3.client("ecs", region_name=config.aws_region)
    sm = boto3.client("secretsmanager", region_name=config.aws_region)
    s3 = boto3.client("s3", region_name=config.aws_region)
    rds = boto3.client("rds", region_name=config.aws_region)

    if "EcsCluster" not in managed_logical_ids:
        cluster_name = get_cluster_name(config.project_name, env_name)
        try:
            cluster_resp = ecs.describe_clusters(clusters=[cluster_name])
            existing_clusters = cluster_resp.get("clusters", [])
            if existing_clusters and existing_clusters[0].get("status") != "INACTIVE":
                collisions.append(
                    "logical resource 'EcsCluster' would be created, but ECS cluster "
                    f"already exists: {cluster_name}"
                )
        except Exception as exc:
            collisions.append(f"Could not verify ECS cluster '{cluster_name}': {exc}")

    for service in config.services:
        if service.image:
            continue
        logical_id = f"EcrRepo{_pascalize(service.name)}"
        if logical_id in managed_logical_ids:
            continue
        repo_name = f"{config.project_name}/{env_name}/{service.name}"
        try:
            ecr.describe_repositories(repositoryNames=[repo_name])
            collisions.append(
                f"logical resource '{logical_id}' would be created, but ECR repository already exists: {repo_name}"
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code != "RepositoryNotFoundException":
                collisions.append(
                    f"Could not verify ECR repository '{repo_name}': {exc}"
                )

    for secret in config.secrets:
        if secret.source.value != "generate":
            continue
        logical_id = f"Secret{_secret_logical_suffix(secret.name)}"
        if logical_id in managed_logical_ids:
            continue
        secret_name = f"/darth-infra/{config.project_name}/{env_name}/{secret.name}"
        try:
            sm.describe_secret(SecretId=secret_name)
            collisions.append(
                f"logical resource '{logical_id}' would be created, but Secrets Manager secret already exists: {secret_name}"
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code != "ResourceNotFoundException":
                collisions.append(f"Could not verify secret '{secret_name}': {exc}")

    for bucket in config.s3_buckets:
        if bucket.mode.value == "existing":
            continue
        logical_id = f"Bucket{bucket.name.replace('-', '')}"
        if logical_id in managed_logical_ids:
            continue
        bucket_name = f"{config.project_name}-{env_name}-{bucket.name}".lower()
        try:
            s3.head_bucket(Bucket=bucket_name)
            collisions.append(
                f"logical resource '{logical_id}' would be created, but S3 bucket name is already in use or accessible: {bucket_name}"
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                continue
            if code in {"403", "Forbidden"}:
                collisions.append(
                    f"logical resource '{logical_id}' would be created, but S3 bucket name is already owned by another account or inaccessible: {bucket_name}"
                )

    if config.rds:
        if "RdsCredentialsSecret" not in managed_logical_ids:
            rds_secret_name = f"{config.project_name}-{env_name}-rds-credentials"
            try:
                sm.describe_secret(SecretId=rds_secret_name)
                collisions.append(
                    "logical resource 'RdsCredentialsSecret' would be created, but Secrets Manager secret already exists: "
                    f"{rds_secret_name}"
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code != "ResourceNotFoundException":
                    collisions.append(
                        f"Could not verify RDS credentials secret '{rds_secret_name}': {exc}"
                    )

        if "Database" not in managed_logical_ids:
            db_identifier = f"{config.project_name}-{env_name}-db"
            try:
                rds.describe_db_instances(DBInstanceIdentifier=db_identifier)
                collisions.append(
                    "logical resource 'Database' would be created, but RDS instance identifier already exists: "
                    f"{db_identifier}"
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"DBInstanceNotFound", "DBInstanceNotFoundFault"}:
                    collisions.append(
                        f"Could not verify RDS instance '{db_identifier}': {exc}"
                    )

    if not collisions:
        return None

    details = "\n  - " + "\n  - ".join(collisions)
    return (
        "Deploy blocked before CloudFormation update because this template update would create "
        "named resources that already exist outside the stack. "
        "CloudFormation cannot auto-adopt existing resources during a normal update. "
        f"Conflicts:{details}\n"
        "Resolve by importing the resources into this stack, reusing existing resources via config, "
        "or renaming/removing conflicting resources."
    )


def _stack_logical_resource_ids(cf, stack_name: str) -> set[str]:
    logical_ids: set[str] = set()
    paginator = cf.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=stack_name):
        for summary in page.get("StackResourceSummaries", []):
            logical_id = str(summary.get("LogicalResourceId", "")).strip()
            if logical_id:
                logical_ids.add(logical_id)
    return logical_ids


def _pascalize(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _secret_logical_suffix(secret_name: str) -> str:
    return secret_name.replace("_", "").replace("-", "")


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


def cancel_stack_update(config: ProjectConfig, env_name: str) -> int:
    cf = boto3.client("cloudformation", region_name=config.aws_region)
    stack_name = f"{config.project_name}-ecs-{env_name}"

    try:
        stack = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        message = str(exc.response.get("Error", {}).get("Message", ""))
        if code == "ValidationError" and "does not exist" in message:
            console.print(f"[red]Stack '{stack_name}' does not exist.[/red]")
            return 1
        console.print(f"[red]Could not inspect stack '{stack_name}': {exc}[/red]")
        return 1

    stack_status = str(stack.get("StackStatus", "UNKNOWN"))
    cancellable_statuses = {
        "UPDATE_IN_PROGRESS",
        "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
    }
    if stack_status not in cancellable_statuses:
        console.print(
            f"[yellow]Stack '{stack_name}' is '{stack_status}', so there is no in-progress update to cancel.[/yellow]"
        )
        return 1

    try:
        cf.cancel_update_stack(StackName=stack_name)
    except ClientError as exc:
        console.print(f"[red]Cancel update failed: {exc}[/red]")
        return 1

    console.print(
        f"[bold]Cancel requested for stack[/bold] [cyan]{stack_name}[/cyan]. Waiting for CloudFormation to settle..."
    )

    terminal_success_statuses = {"UPDATE_ROLLBACK_COMPLETE"}
    last_stack_status: str | None = None
    while True:
        current_status, current_reason = _get_stack_status(cf, stack_name)
        if current_status != last_stack_status:
            if current_reason:
                console.print(
                    f"[bold]Stack status:[/bold] [cyan]{current_status}[/cyan] - {current_reason}"
                )
            else:
                console.print(
                    f"[bold]Stack status:[/bold] [cyan]{current_status}[/cyan]"
                )
            last_stack_status = current_status

        if _is_stack_terminal(current_status):
            if current_status in terminal_success_statuses:
                console.print(
                    f"[green]Update cancellation completed: {current_status}[/green]"
                )
                return 0

            console.print(
                f"[red]Stack reached terminal status after cancel request: {current_status}[/red]"
            )
            return 1

        time.sleep(5)


def _wait_for_changeset(cf, cs_arn: str) -> tuple[str, str, list[dict]]:
    while True:
        desc = cf.describe_change_set(ChangeSetName=cs_arn)
        status = desc.get("Status", "")
        reason = desc.get("StatusReason", "")
        if status in {"CREATE_COMPLETE", "FAILED"}:
            return status, reason, desc.get("Changes", [])
        time.sleep(2)


def _print_changeset_failure_diagnostics(cf, cs_arn: str, stack_name: str) -> None:
    try:
        details = cf.describe_change_set(ChangeSetName=cs_arn, StackName=stack_name)
    except Exception as exc:
        console.print(f"[yellow]Could not load change set details: {exc}[/yellow]")
        return

    execution_status = details.get("ExecutionStatus")
    status_reason = details.get("StatusReason")
    if execution_status:
        console.print(f"[dim]Change set execution status: {execution_status}[/dim]")
    if status_reason:
        console.print(f"[dim]Change set status reason: {status_reason}[/dim]")

    try:
        hooks: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            args: dict[str, str] = {
                "ChangeSetName": cs_arn,
                "StackName": stack_name,
            }
            if next_token:
                args["NextToken"] = next_token

            response = cf.describe_change_set_hooks(**args)
            hooks.extend(response.get("Hooks", []))
            next_token = response.get("NextToken")
            if not next_token:
                break

        if not hooks:
            _print_recent_stack_events(
                cf,
                stack_name,
                label=f"Stack events for {stack_name}",
                max_events=15,
            )
            return

        console.print("[bold]Hook validation details:[/bold]")
        for hook in hooks:
            hook_name = (
                hook.get("HookTypeName")
                or hook.get("TypeName")
                or hook.get("HookName")
                or "unknown-hook"
            )
            hook_status = hook.get("HookStatus") or hook.get("Status") or "UNKNOWN"
            reason = (
                hook.get("HookStatusReason")
                or hook.get("StatusReason")
                or hook.get("FailureMode")
                or ""
            )

            target_details = hook.get("TargetDetails")
            target_summary = ""
            if isinstance(target_details, dict) and target_details:
                target_logical_id = target_details.get("TargetLogicalId")
                target_type = target_details.get("TargetType")
                if target_logical_id and target_type:
                    target_summary = f" target={target_logical_id} ({target_type})"
                elif target_logical_id:
                    target_summary = f" target={target_logical_id}"
                else:
                    target_summary = f" target={json.dumps(target_details)}"

            if reason:
                console.print(
                    f"- {hook_name} [{hook_status}]{target_summary} - {reason}"
                )
            else:
                console.print(f"- {hook_name} [{hook_status}]{target_summary}")
    except Exception as exc:
        console.print(
            f"[yellow]Could not load detailed hook validation results: {exc}[/yellow]"
        )
        _print_recent_stack_events(
            cf,
            stack_name,
            label=f"Stack events for {stack_name}",
            max_events=15,
        )


def _print_recent_stack_events(
    cf,
    stack_name: str,
    *,
    label: str,
    max_events: int,
) -> None:
    try:
        events = cf.describe_stack_events(StackName=stack_name).get("StackEvents", [])
    except ClientError as exc:
        console.print(f"[yellow]Could not load events for {label}: {exc}[/yellow]")
        return

    if not events:
        return

    recent = sorted(
        events,
        key=lambda event: _event_datetime_sort_key(event.get("Timestamp")),
    )[-max_events:]
    if not recent:
        return

    console.print(f"[bold]Recent CloudFormation events ({label}):[/bold]")
    for event in recent:
        logical_id = event.get("LogicalResourceId", "?")
        resource_type = event.get("ResourceType", "?")
        status = event.get("ResourceStatus", "?")
        reason = event.get("ResourceStatusReason")
        if reason:
            console.print(f"- {logical_id} ({resource_type}) [{status}] - {reason}")
        else:
            console.print(f"- {logical_id} ({resource_type}) [{status}]")


def _monitor_stack_deploy(
    *,
    cf,
    config: ProjectConfig,
    env_name: str,
    stack_name: str,
    poll_interval_seconds: int,
) -> bool:
    ecs = boto3.client("ecs", region_name=config.aws_region)
    logs = boto3.client("logs", region_name=config.aws_region)
    state = DeployMonitorState(
        seen_stack_event_ids=set(),
        seen_service_event_keys=set(),
        seen_task_failure_keys=set(),
        log_since_ms_by_service={},
        last_pending_signature="",
        fatal_ecs_messages=[],
    )

    last_stack_status: str | None = None
    final_status: str = "UNKNOWN"
    final_reason: str = ""
    success = False
    rollout_deadline = time.time() + 900

    with Live(console=console, refresh_per_second=4, transient=False) as live:
        while True:
            stack_status, stack_reason = _get_stack_status(cf, stack_name)
            if stack_status != last_stack_status:
                last_stack_status = stack_status

            stack_events = _collect_new_stack_events(cf, stack_name, state)
            incomplete = _collect_incomplete_resources(cf, stack_name)
            ecs_snapshot = _collect_ecs_deploy_observability(
                config=config,
                env_name=env_name,
                ecs=ecs,
                logs=logs,
                state=state,
            )

            live.update(
                _render_deploy_live_view(
                    stack_name=stack_name,
                    stack_status=stack_status,
                    stack_reason=stack_reason,
                    stack_events=stack_events,
                    incomplete_resources=incomplete,
                    ecs_snapshot=ecs_snapshot,
                )
            )

            if _is_stack_terminal(stack_status):
                final_status = stack_status
                final_reason = stack_reason
                success = _is_stack_success(stack_status)
                if not success:
                    break
                if state.fatal_ecs_messages:
                    final_reason = state.fatal_ecs_messages[-1]
                    success = False
                    break
                if _ecs_rollout_is_stable(ecs_snapshot):
                    break
                if time.time() >= rollout_deadline:
                    final_reason = _ecs_rollout_timeout_reason(ecs_snapshot)
                    success = False
                    break

            time.sleep(poll_interval_seconds)

    if success:
        console.print(
            f"[green]Stack reached terminal success state: {final_status}[/green]"
        )
        return True

    if final_reason:
        console.print(
            f"[red]Stack reached terminal failure state: {final_status} - {final_reason}[/red]"
        )
    else:
        console.print(
            f"[red]Stack reached terminal failure state: {final_status}[/red]"
        )
    return False


def _get_stack_status(cf, stack_name: str) -> tuple[str, str]:
    try:
        stack = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as exc:
        return "UNKNOWN", str(exc)
    return str(stack.get("StackStatus", "UNKNOWN")), str(
        stack.get("StackStatusReason", "")
    )


def _is_stack_terminal(status: str) -> bool:
    if not status:
        return False
    if status == "UNKNOWN":
        return False
    if status == "REVIEW_IN_PROGRESS":
        return False
    return "IN_PROGRESS" not in status


def _is_stack_success(status: str) -> bool:
    return status in {
        "CREATE_COMPLETE",
        "UPDATE_COMPLETE",
        "IMPORT_COMPLETE",
    }


def _collect_new_stack_events(
    cf,
    stack_name: str,
    state: DeployMonitorState,
    *,
    max_events: int = 12,
) -> list[dict[str, str]]:
    try:
        events = cf.describe_stack_events(StackName=stack_name).get("StackEvents", [])
    except ClientError as exc:
        return [{"summary": f"Could not load stack events: {exc}", "style": "yellow"}]

    new_events: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("EventId", "")).strip()
        if not event_id or event_id in state.seen_stack_event_ids:
            continue
        state.seen_stack_event_ids.add(event_id)
        new_events.append(event)

    if not new_events:
        return []

    new_events.sort(key=lambda event: _event_datetime_sort_key(event.get("Timestamp")))
    trimmed = new_events[-max_events:]

    output: list[dict[str, str]] = []
    for event in trimmed:
        logical_id = event.get("LogicalResourceId", "?")
        resource_type = event.get("ResourceType", "?")
        status = event.get("ResourceStatus", "?")
        reason = event.get("ResourceStatusReason")
        if reason:
            output.append(
                {
                    "summary": f"{logical_id} ({resource_type}) [{status}] - {reason}",
                    "style": "red" if "FAILED" in str(status) else "white",
                }
            )
        else:
            output.append(
                {
                    "summary": f"{logical_id} ({resource_type}) [{status}]",
                    "style": "red" if "FAILED" in str(status) else "white",
                }
            )
    return output


def _print_incomplete_resource_summary(
    cf,
    stack_name: str,
    state: DeployMonitorState,
    *,
    max_rows: int = 30,
) -> None:
    incomplete = _collect_incomplete_resources(cf, stack_name)
    signature = "|".join(
        f"{item['stack']}::{item['logical_id']}::{item['status']}"
        for item in incomplete
    )
    if signature == state.last_pending_signature:
        if incomplete:
            console.print(f"[dim]Resources still not complete: {len(incomplete)}[/dim]")
        return
    state.last_pending_signature = signature

    if not incomplete:
        console.print(
            "[green]All CloudFormation resources are in complete states.[/green]"
        )
        return

    console.print(f"[bold]Resources not yet complete:[/bold] {len(incomplete)}")
    for item in incomplete[:max_rows]:
        reason = item.get("reason")
        stack_label = item["stack"]
        if reason:
            console.print(
                f"- [{stack_label}] {item['logical_id']} ({item['type']}) [{item['status']}] - {reason}"
            )
        else:
            console.print(
                f"- [{stack_label}] {item['logical_id']} ({item['type']}) [{item['status']}]"
            )
    remaining = len(incomplete) - max_rows
    if remaining > 0:
        console.print(f"[dim]... and {remaining} more resources[/dim]")


def _collect_incomplete_resources(cf, stack_name: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    visited: set[str] = set()
    _collect_incomplete_resources_recursive(
        cf=cf,
        stack_name=stack_name,
        stack_label=stack_name,
        visited=visited,
        out=out,
    )
    out.sort(key=lambda item: (item["stack"], item["logical_id"]))
    return out


def _collect_incomplete_resources_recursive(
    *,
    cf,
    stack_name: str,
    stack_label: str,
    visited: set[str],
    out: list[dict[str, str]],
) -> None:
    if stack_name in visited:
        return
    visited.add(stack_name)

    try:
        paginator = cf.get_paginator("list_stack_resources")
        summaries: list[dict[str, Any]] = []
        for page in paginator.paginate(StackName=stack_name):
            summaries.extend(page.get("StackResourceSummaries", []))
    except ClientError:
        return

    for summary in summaries:
        status = str(summary.get("ResourceStatus", ""))
        if _is_resource_incomplete(status):
            out.append(
                {
                    "stack": stack_label,
                    "logical_id": str(summary.get("LogicalResourceId", "?")),
                    "type": str(summary.get("ResourceType", "?")),
                    "status": status,
                    "reason": str(summary.get("ResourceStatusReason", "")),
                }
            )

        if summary.get("ResourceType") != "AWS::CloudFormation::Stack":
            continue
        nested_stack_id = str(summary.get("PhysicalResourceId", "")).strip()
        nested_logical_id = str(summary.get("LogicalResourceId", "nested"))
        if not nested_stack_id or nested_stack_id == "None":
            continue
        _collect_incomplete_resources_recursive(
            cf=cf,
            stack_name=nested_stack_id,
            stack_label=nested_logical_id,
            visited=visited,
            out=out,
        )


def _is_resource_incomplete(status: str) -> bool:
    if not status:
        return True
    if status.endswith("_COMPLETE"):
        return False
    return status != "DELETE_COMPLETE"


def _collect_ecs_deploy_observability(
    *,
    config: ProjectConfig,
    env_name: str,
    ecs,
    logs,
    state: DeployMonitorState,
) -> dict[str, Any]:
    if not config.services:
        return {"rows": [], "messages": []}

    cluster = get_cluster_name(config.project_name, env_name)
    short_to_full_service_name = {
        service.name: get_service_name(config.project_name, env_name, service.name)
        for service in config.services
    }

    services_by_name: dict[str, dict[str, Any]] = {}
    full_names = list(short_to_full_service_name.values())

    try:
        for idx in range(0, len(full_names), 10):
            chunk = full_names[idx : idx + 10]
            resp = ecs.describe_services(cluster=cluster, services=chunk)
            for service in resp.get("services", []):
                name = str(service.get("serviceName", ""))
                if name:
                    services_by_name[name] = service
    except ClientError as exc:
        return {
            "rows": [],
            "messages": [
                {
                    "key": "ECS status",
                    "value": f"Could not load ECS service status: {exc}",
                    "style": "yellow",
                }
            ],
        }

    rows: list[dict[str, str]] = []
    messages: list[dict[str, str]] = []
    for service_cfg in config.services:
        short_name = service_cfg.name
        full_name = short_to_full_service_name[short_name]
        service = services_by_name.get(full_name)
        if not service:
            rows.append(
                {
                    "service": short_name,
                    "status": "NOT_FOUND",
                    "running": "0",
                    "desired": "0",
                    "pending": "0",
                    "deployments": "0",
                }
            )
            messages.append(
                {
                    "key": f"{short_name} service",
                    "value": "Service not found yet",
                    "style": "yellow",
                }
            )
            continue

        running = int(service.get("runningCount", 0))
        desired = int(service.get("desiredCount", 0))
        pending = int(service.get("pendingCount", 0))
        status = str(service.get("status", "UNKNOWN"))
        deployment_count = len(service.get("deployments", []))
        rows.append(
            {
                "service": short_name,
                "status": status,
                "running": str(running),
                "desired": str(desired),
                "pending": str(pending),
                "deployments": str(deployment_count),
            }
        )

        deployments = service.get("deployments", [])
        for deployment in deployments:
            rollout = deployment.get("rolloutState", "UNKNOWN")
            rollout_reason = deployment.get("rolloutStateReason", "")
            task_def = str(deployment.get("taskDefinition", "")).split("/")[-1]
            desired_deployment = int(deployment.get("desiredCount", 0))
            running_deployment = int(deployment.get("runningCount", 0))
            pending_deployment = int(deployment.get("pendingCount", 0))
            line = (
                f"  deployment taskDef={task_def} rollout={rollout} "
                f"running={running_deployment}/{desired_deployment} pending={pending_deployment}"
            )
            if rollout_reason:
                line = f"{line} - {rollout_reason}"
            messages.append(
                {
                    "key": f"{short_name} deployment",
                    "value": line.strip(),
                    "style": "dim",
                }
            )

        messages.extend(_collect_new_ecs_service_events(short_name, service, state))
        messages.extend(
            _collect_recent_task_failures(
                cluster,
                full_name,
                short_name,
                ecs,
                state,
            )
        )

        is_deploying = pending > 0 or running < desired or deployment_count > 1
        if is_deploying:
            messages.extend(
                _collect_recent_service_logs(
                    config=config,
                    env_name=env_name,
                    service_name=short_name,
                    logs=logs,
                    state=state,
                )
            )

    return {"rows": rows, "messages": messages}


def _collect_new_ecs_service_events(
    service_name: str,
    service: dict[str, Any],
    state: DeployMonitorState,
    *,
    max_events: int = 5,
) -> list[dict[str, str]]:
    raw_events = service.get("events", [])
    if not isinstance(raw_events, list):
        return []

    new_events: list[dict[str, Any]] = []
    for event in raw_events:
        created_at = event.get("createdAt")
        message = str(event.get("message", "")).strip()
        if not message:
            continue
        key = f"{service_name}|{created_at}|{message}"
        if key in state.seen_service_event_keys:
            continue
        state.seen_service_event_keys.add(key)
        new_events.append(event)

    if not new_events:
        return []

    new_events.sort(key=lambda event: _event_datetime_sort_key(event.get("createdAt")))
    output: list[dict[str, str]] = []
    for event in new_events[-max_events:]:
        message = str(event.get("message", "")).strip()
        lowered = message.lower()
        style = (
            "red"
            if any(k in lowered for k in ("error", "failed", "unable", "unhealthy"))
            else "yellow"
        )
        if _is_fatal_ecs_startup_message(message):
            state.fatal_ecs_messages.append(f"{service_name}: {message}")
        output.append(
            {"key": f"{service_name} event", "value": message, "style": style}
        )
    return output


def _collect_recent_task_failures(
    cluster: str,
    full_service_name: str,
    short_service_name: str,
    ecs,
    state: DeployMonitorState,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    try:
        stopped_tasks = ecs.list_tasks(
            cluster=cluster,
            serviceName=full_service_name,
            desiredStatus="STOPPED",
            maxResults=5,
        ).get("taskArns", [])
    except ClientError:
        return output

    if not stopped_tasks:
        return output

    try:
        described = ecs.describe_tasks(cluster=cluster, tasks=stopped_tasks).get(
            "tasks", []
        )
    except ClientError:
        return output

    for task in described:
        task_arn = str(task.get("taskArn", ""))
        if not task_arn:
            continue
        task_id = task_arn.split("/")[-1]
        stopped_reason = str(task.get("stoppedReason", "")).strip()
        if stopped_reason:
            key = f"{task_arn}|{stopped_reason}"
            if key not in state.seen_task_failure_keys:
                state.seen_task_failure_keys.add(key)
                if _is_fatal_ecs_startup_message(stopped_reason):
                    state.fatal_ecs_messages.append(
                        f"{short_service_name} task stopped ({task_id}): {stopped_reason}"
                    )
                output.append(
                    {
                        "key": f"{short_service_name} task",
                        "value": f"stopped ({task_id}): {stopped_reason}",
                        "style": "red",
                    }
                )

        containers = task.get("containers", [])
        for container in containers:
            name = str(container.get("name", ""))
            reason = str(container.get("reason", "")).strip()
            if not reason:
                continue
            key = f"{task_arn}|{name}|{reason}"
            if key in state.seen_task_failure_keys:
                continue
            state.seen_task_failure_keys.add(key)
            if _is_fatal_ecs_startup_message(reason):
                state.fatal_ecs_messages.append(
                    f"{short_service_name} container issue ({task_id}/{name}): {reason}"
                )
            output.append(
                {
                    "key": f"{short_service_name} container",
                    "value": f"issue ({task_id}/{name}): {reason}",
                    "style": "red",
                }
            )
    return output


def _collect_recent_service_logs(
    *,
    config: ProjectConfig,
    env_name: str,
    service_name: str,
    logs,
    state: DeployMonitorState,
    max_events: int = 20,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    log_group = f"/ecs/{config.project_name}-{env_name}-{service_name}"
    now_ms = int(time.time() * 1000)
    since_ms = state.log_since_ms_by_service.get(service_name, now_ms - 120000)

    try:
        response = logs.filter_log_events(
            logGroupName=log_group,
            startTime=since_ms,
            limit=max_events,
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "ResourceNotFoundException":
            return output
        output.append(
            {
                "key": f"{service_name} logs",
                "value": f"Could not read logs ({log_group}): {exc}",
                "style": "yellow",
            }
        )
        return output

    events = response.get("events", [])
    if not events:
        return output

    max_seen_timestamp = since_ms
    for event in events:
        timestamp = int(event.get("timestamp", since_ms))
        message = str(event.get("message", "")).rstrip()
        if not message:
            continue
        if timestamp > max_seen_timestamp:
            max_seen_timestamp = timestamp

        lowered = message.lower()
        style = (
            "red"
            if any(
                keyword in lowered
                for keyword in ("error", "exception", "failed", "traceback")
            )
            else "dim"
        )
        output.append(
            {
                "key": f"{service_name} log",
                "value": message,
                "style": style,
            }
        )

    state.log_since_ms_by_service[service_name] = max_seen_timestamp + 1
    return output


def _is_fatal_ecs_startup_message(message: str) -> bool:
    lowered = message.lower()
    if "resourceinitializationerror" in lowered:
        return True
    return any(
        needle in lowered
        for needle in (
            "unable to pull secrets",
            "unable to retrieve secret",
            "accessdeniedexception",
            "secretsmanager:getsecretvalue",
            "pull secrets or registry auth",
            "failed to fetch secret",
        )
    )


def _ecs_rollout_is_stable(ecs_snapshot: dict[str, Any]) -> bool:
    for row in ecs_snapshot.get("rows", []):
        desired = int(row.get("desired", "0"))
        running = int(row.get("running", "0"))
        pending = int(row.get("pending", "0"))
        deployments = int(row.get("deployments", "0"))
        status = str(row.get("status", "UNKNOWN"))
        if desired == 0:
            continue
        if status != "ACTIVE":
            return False
        if running < desired or pending > 0 or deployments > 1:
            return False
    return True


def _ecs_rollout_timeout_reason(ecs_snapshot: dict[str, Any]) -> str:
    unstable = []
    for row in ecs_snapshot.get("rows", []):
        desired = int(row.get("desired", "0"))
        if desired == 0:
            continue
        running = int(row.get("running", "0"))
        pending = int(row.get("pending", "0"))
        deployments = int(row.get("deployments", "0"))
        status = str(row.get("status", "UNKNOWN"))
        if status == "ACTIVE" and running >= desired and pending == 0 and deployments <= 1:
            continue
        unstable.append(
            f"{row.get('service', '?')} status={status} running={running}/{desired} "
            f"pending={pending} deployments={deployments}"
        )
    if not unstable:
        return "ECS rollout did not stabilize before timeout"
    return "ECS rollout did not stabilize before timeout: " + "; ".join(unstable)


def _render_deploy_live_view(
    *,
    stack_name: str,
    stack_status: str,
    stack_reason: str,
    stack_events: list[dict[str, str]],
    incomplete_resources: list[dict[str, str]],
    ecs_snapshot: dict[str, Any],
) -> Group:
    stack_kv = _build_key_value_table(
        "Stack",
        [
            ("Name", stack_name, "cyan"),
            ("Status", stack_status, "cyan"),
            (
                "Reason",
                stack_reason if stack_reason else "-",
                "dim" if not stack_reason else "white",
            ),
            ("Pending resources", str(len(incomplete_resources)), "yellow"),
        ],
    )

    ecs_table = Table(title="ECS Deploy Progress", expand=True)
    ecs_table.add_column("Service", style="cyan")
    ecs_table.add_column("Status")
    ecs_table.add_column("Running", justify="right")
    ecs_table.add_column("Desired", justify="right")
    ecs_table.add_column("Pending", justify="right")
    ecs_table.add_column("Deployments", justify="right")

    for row in ecs_snapshot.get("rows", []):
        status_value = str(row.get("status", "UNKNOWN"))
        status_style = "green" if status_value == "ACTIVE" else "yellow"
        ecs_table.add_row(
            str(row.get("service", "-")),
            f"[{status_style}]{status_value}[/{status_style}]",
            str(row.get("running", "0")),
            str(row.get("desired", "0")),
            str(row.get("pending", "0")),
            str(row.get("deployments", "0")),
        )

    if not ecs_snapshot.get("rows"):
        ecs_table.add_row("-", "-", "0", "0", "0", "0")

    events_rows: list[tuple[str, str, str]] = []
    if stack_events:
        for event in stack_events[-8:]:
            events_rows.append(
                ("Stack event", event.get("summary", ""), event.get("style", "white"))
            )
    else:
        events_rows.append(("Stack event", "No new events", "dim"))

    for item in incomplete_resources[:8]:
        reason = str(item.get("reason", "")).strip()
        summary = f"[{item.get('stack', '?')}] {item.get('logical_id', '?')} ({item.get('type', '?')}) [{item.get('status', '?')}]"
        if reason:
            summary = f"{summary} - {reason}"
        events_rows.append(("Pending", summary, "yellow"))

    if len(incomplete_resources) > 8:
        events_rows.append(
            (
                "Pending",
                f"... and {len(incomplete_resources) - 8} more resources",
                "dim",
            )
        )

    for message in ecs_snapshot.get("messages", [])[-16:]:
        events_rows.append(
            (
                str(message.get("key", "Info")),
                str(message.get("value", "")),
                str(message.get("style", "white")),
            )
        )

    activity_kv = _build_key_value_table("Activity", events_rows)

    return Group(
        Panel(stack_kv, border_style="cyan"),
        Panel(ecs_table, border_style="green"),
        Panel(activity_kv, border_style="magenta"),
    )


def _build_key_value_table(
    title: str,
    rows: list[tuple[str, str, str]],
) -> Table:
    table = Table(title=title, expand=True, show_header=False)
    table.add_column("Key", style="bold cyan", no_wrap=True, width=22)
    table.add_column("Value", overflow="fold")
    for key, value, style in rows:
        table.add_row(key, f"[{style}]{value}[/{style}]")
    return table


def _event_datetime_sort_key(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0


def _print_stack_failure_details(cf, stack_name: str) -> None:
    try:
        stack_desc = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as exc:
        console.print(
            f"[red]Could not load stack details for '{stack_name}': {exc}[/red]"
        )
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
        _print_failed_events(
            cf, nested_stack_id, label=f"Nested stack ({nested_stack_id})"
        )


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


def _resolve_network(
    config: ProjectConfig, ec2
) -> tuple[str, str, list[str], list[str]]:
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
        raise RuntimeError(
            "Could not resolve public subnets required for dedicated ALB"
        )

    if not vpc_cidr:
        raise RuntimeError(f"Could not resolve CIDR block for VPC {vpc_id}")

    return vpc_id, vpc_cidr, private_subnets, public_subnets


def _resolve_shared_alb(config: ProjectConfig, elbv2) -> tuple[str, str, str]:
    if config.alb.mode.value != "shared":
        return "", "", ""

    listener_arn = config.alb.shared_listener_arn
    alb_sg = config.alb.shared_alb_security_group_id
    if listener_arn and alb_sg:
        listeners = elbv2.describe_listeners(ListenerArns=[listener_arn]).get(
            "Listeners", []
        )
        if len(listeners) != 1:
            raise RuntimeError(
                f"Expected one listener for ARN {listener_arn}, found {len(listeners)}"
            )
        listener = listeners[0]
        listener_protocol = str(listener.get("Protocol", "")).strip().upper()
        listener_port = listener.get("Port")
        if config.cloudfront.enabled and config.cloudfront.origin_https_only:
            if listener_protocol != "HTTPS" or listener_port != 443:
                raise RuntimeError(
                    "cloudfront.origin_https_only requires shared ALB listener HTTPS:443, "
                    f"but resolved listener is {listener_protocol or 'unknown'}:{listener_port}"
                )
        lb_arn = listener.get("LoadBalancerArn")
        lbs = elbv2.describe_load_balancers(LoadBalancerArns=[lb_arn]).get(
            "LoadBalancers", []
        )
        if len(lbs) != 1:
            raise RuntimeError(
                f"Expected one ALB for listener {listener_arn}, found {len(lbs)}"
            )
        return listener_arn, alb_sg, lbs[0].get("DNSName", "")

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
    if not preferred and not (
        config.cloudfront.enabled and config.cloudfront.origin_https_only
    ):
        preferred = next((l for l in listeners if l.get("Port") in {80, 443}), None)
    if not preferred:
        if config.cloudfront.enabled and config.cloudfront.origin_https_only:
            raise RuntimeError(
                "cloudfront.origin_https_only requires a shared ALB HTTPS listener on port 443"
            )
        raise RuntimeError("Could not find an ALB listener to attach rules")

    return preferred["ListenerArn"], alb_sg, alb.get("DNSName", "")


def _resolve_listener_priorities(
    config: ProjectConfig,
    env_name: str,
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

    if _stack_exists_for_env(config, env_name):
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

    stack_owned = _resolve_stack_owned_listener_rule_priorities(
        config, env_name, listener_arn, elbv2
    )

    conflicts = sorted(
        priority
        for priority in desired_priorities.values()
        if priority in existing and priority not in stack_owned
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


def _resolve_stack_owned_listener_rule_priorities(
    config: ProjectConfig,
    env_name: str,
    listener_arn: str,
    elbv2,
) -> set[int]:
    stack_name = f"{config.project_name}-ecs-{env_name}"
    cf = boto3.client("cloudformation", region_name=config.aws_region)

    rule_arns = _list_listener_rule_arns_for_stack(cf, stack_name)

    priorities: set[int] = set()
    for rule_arn in rule_arns:
        try:
            response = elbv2.describe_rules(RuleArns=[rule_arn])
        except ClientError:
            continue
        except Exception:
            continue

        for rule in response.get("Rules", []):
            if str(rule.get("ListenerArn", "")).strip() != listener_arn:
                continue
            priority = rule.get("Priority")
            if not priority or priority == "default":
                continue
            try:
                priorities.add(int(priority))
            except ValueError:
                continue

    return priorities


def _list_listener_rule_arns_for_stack(
    cf,
    stack_name: str,
    visited: set[str] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()
    if stack_name in visited:
        return []
    visited.add(stack_name)

    try:
        stack_resources = _list_stack_resource_summaries(cf, stack_name)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        message = str(exc.response.get("Error", {}).get("Message", ""))
        if code == "ValidationError" and "does not exist" in message:
            return []
        return []
    except Exception:
        return []

    listener_rule_arns: list[str] = []
    nested_stacks: list[str] = []
    for summary in stack_resources:
        resource_type = str(summary.get("ResourceType", "")).strip()
        physical_id = str(summary.get("PhysicalResourceId", "")).strip()
        if not physical_id:
            continue
        if resource_type == "AWS::ElasticLoadBalancingV2::ListenerRule":
            listener_rule_arns.append(physical_id)
        elif resource_type == "AWS::CloudFormation::Stack":
            nested_stacks.append(physical_id)

    for nested_stack_id in nested_stacks:
        listener_rule_arns.extend(
            _list_listener_rule_arns_for_stack(cf, nested_stack_id, visited)
        )

    return listener_rule_arns


def _list_stack_resource_summaries(cf, stack_name: str) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    paginator = cf.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=stack_name):
        summaries.extend(page.get("StackResourceSummaries", []))
    return summaries


def _stack_exists_for_env(config: ProjectConfig, env_name: str) -> bool:
    stack_name = f"{config.project_name}-ecs-{env_name}"
    cf = boto3.client("cloudformation", region_name=config.aws_region)
    try:
        cf.describe_stacks(StackName=stack_name)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        message = str(exc.response.get("Error", {}).get("Message", ""))
        if code == "ValidationError" and "does not exist" in message:
            return False
        raise


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


def _resolve_external_secrets(config: ProjectConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    sm = boto3.client("secretsmanager", region_name=config.aws_region)
    for sec in config.secrets:
        if sec.source.value in {"generate", "rds"}:
            continue

        if sec.source.value == "env":
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
            continue

        if sec.source.value == "existing":
            value = (sec.existing_secret_name or "").strip()
            if not value:
                raise RuntimeError(
                    f"Secret '{sec.name}' source is 'existing' but existing_secret_name is empty"
                )
            if value.startswith("arn:"):
                out[sec.name] = value
                continue
            info = sm.describe_secret(SecretId=value)
            out[sec.name] = info["ARN"]
            continue

        raise RuntimeError(f"Unsupported secret source '{sec.source.value}'")
    return out


def _resolve_existing_service_discovery_namespace(
    config: ProjectConfig,
    servicediscovery,
    route53,
    vpc_id: str,
) -> str:
    if not any(s.enable_service_discovery for s in config.services):
        return ""

    try:
        resp = servicediscovery.list_namespaces(
            Filters=[
                {"Name": "TYPE", "Values": ["DNS_PRIVATE"], "Condition": "EQ"},
                {"Name": "NAME", "Values": ["local"], "Condition": "EQ"},
            ]
        )
    except Exception:
        return ""

    for ns in resp.get("Namespaces", []):
        namespace_id = str(ns.get("Id", "")).strip()
        if not namespace_id:
            continue
        try:
            details = servicediscovery.get_namespace(Id=namespace_id)
            hosted_zone_id = (
                details.get("Namespace", {})
                .get("Properties", {})
                .get("DnsProperties", {})
                .get("HostedZoneId")
            )
            if not hosted_zone_id:
                continue

            hosted_zone = route53.get_hosted_zone(Id=hosted_zone_id)
            for associated_vpc in hosted_zone.get("VPCs", []):
                if (
                    associated_vpc.get("VPCId") == vpc_id
                    and associated_vpc.get("VPCRegion") == config.aws_region
                ):
                    return namespace_id
        except Exception:
            continue

    return ""


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
            "ParameterKey": "SharedAlbDnsName",
            "ParameterValue": lookups.shared_alb_dns_name,
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
        if sec.source.value in {"generate", "rds"}:
            continue
        key = f"EnvSecretArn{sec.name.replace('_', '').replace('-', '')}"
        params.append(
            {
                "ParameterKey": key,
                "ParameterValue": lookups.external_secret_arns.get(sec.name, ""),
            }
        )

    if any(s.enable_service_discovery for s in config.services):
        params.append(
            {
                "ParameterKey": "ExistingCloudMapNamespaceId",
                "ParameterValue": lookups.existing_service_discovery_namespace_id,
            }
        )

    return params


def run_seed_copy_tasks(config: ProjectConfig, env_name: str) -> int:
    seed_buckets = [
        bucket
        for bucket in config.s3_buckets
        if bucket.mode.value == "seed-copy" and bucket.seed_source_bucket_name
    ]
    if not seed_buckets:
        return 0

    s3 = boto3.client("s3", region_name=config.aws_region)
    failures: list[str] = []

    for bucket in seed_buckets:
        if env_name == "prod" and bucket.seed_non_prod_only:
            console.print(
                f"[dim]Skipping seed copy for bucket '{bucket.name}' in prod (seed_non_prod_only=true).[/dim]"
            )
            continue

        source_bucket = str(bucket.seed_source_bucket_name).strip()
        target_bucket = f"{config.project_name}-{env_name}-{bucket.name}".lower()
        marker_key = f".darth-infra/seed-copy/{bucket.name}.json"

        if source_bucket == target_bucket:
            console.print(
                f"[yellow]Skipping seed copy for bucket '{bucket.name}' because source and target are identical ({source_bucket}).[/yellow]"
            )
            continue

        try:
            _ensure_bucket_exists(s3, source_bucket, role="source")
            _ensure_bucket_exists(s3, target_bucket, role="target")

            if _seed_marker_exists(s3, target_bucket, marker_key):
                console.print(
                    f"[dim]Seed copy already completed for bucket '{bucket.name}' ({target_bucket}); skipping.[/dim]"
                )
                continue

            cmd = [
                "aws",
                "s3",
                "sync",
                f"s3://{source_bucket}",
                f"s3://{target_bucket}",
                "--region",
                config.aws_region,
            ]
            console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
            result = subprocess.run(cmd)
            if result.returncode != 0:
                raise RuntimeError(
                    f"aws s3 sync failed for '{bucket.name}' with exit code {result.returncode}"
                )

            marker_payload = {
                "bucket": bucket.name,
                "source_bucket": source_bucket,
                "target_bucket": target_bucket,
                "seeded_for_environment": env_name,
            }
            s3.put_object(
                Bucket=target_bucket,
                Key=marker_key,
                Body=json.dumps(marker_payload, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
            console.print(
                f"[green]Seed copy completed for bucket '{bucket.name}' ({source_bucket} -> {target_bucket})[/green]"
            )
        except Exception as exc:
            failures.append(f"{bucket.name}: {exc}")

    if failures:
        for failure in failures:
            console.print(f"[red]Seed copy failed: {failure}[/red]")
        return 1

    return 0


def _seed_marker_exists(s3, bucket_name: str, marker_key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket_name, Key=marker_key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _ensure_bucket_exists(s3, bucket_name: str, *, role: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as exc:
        raise RuntimeError(f"{role} bucket '{bucket_name}' is not accessible") from exc
