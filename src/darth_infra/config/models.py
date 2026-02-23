"""Strongly-typed configuration models for darth-infra projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SecretSource(str, Enum):
    """How a secret value is sourced."""

    GENERATE = "generate"
    ENV = "env"


class AlbMode(str, Enum):
    """Whether to use a shared ALB or provision a dedicated one."""

    SHARED = "shared"
    DEDICATED = "dedicated"


class LaunchType(str, Enum):
    """ECS launch type for a service."""

    FARGATE = "fargate"
    EC2 = "ec2"


class Architecture(str, Enum):
    """CPU architecture for EC2-backed ECS tasks."""

    X86_64 = "x86_64"
    ARM64 = "arm64"


# Graviton / ARM-based instance type prefixes
_ARM_PREFIXES = (
    "a1",
    "t4g",
    "m6g",
    "m6gd",
    "m7g",
    "m7gd",
    "c6g",
    "c6gd",
    "c6gn",
    "c7g",
    "c7gd",
    "c7gn",
    "r6g",
    "r6gd",
    "r7g",
    "r7gd",
    "x2gd",
    "im4gn",
    "is4gen",
    "g5g",
    "hpc7g",
)


def detect_architecture(instance_type: str) -> Architecture:
    """Infer CPU architecture from an EC2 instance type string."""
    family = instance_type.split(".")[0]
    if family in _ARM_PREFIXES:
        return Architecture.ARM64
    return Architecture.X86_64


def _rule_param_suffix(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum())
    return cleaned or "Rule"


@dataclass
class SecretConfig:
    """A secret to inject into containers as an environment variable.

    Attributes:
        name: Environment variable name (e.g. DJANGO_SECRET_KEY).
        source: "generate" to auto-create a random value per environment,
                "env" to import an existing Secrets Manager secret whose
                name/ARN is provided in the deployer's local environment.
        length: Character length for generated secrets.
        generate_once: If True, the value is created once per environment and
                       reused across deploys.
    """

    name: str
    source: SecretSource = SecretSource.GENERATE
    length: int = 50
    generate_once: bool = True


@dataclass
class S3BucketConfig:
    """An S3 bucket to provision per environment.

    Attributes:
        name: Logical name. Actual bucket: ``{project}-{env}-{name}``.
        public_read: Grant public read access.
        cloudfront: Provision a CloudFront distribution in front of this bucket.
        cors: Enable permissive CORS headers.
    """

    name: str
    public_read: bool = False
    cloudfront: bool = False
    cors: bool = False


@dataclass
class RdsConfig:
    """Optional RDS PostgreSQL instance configuration.

    Attributes:
        database_name: Name of the initial database.
        instance_type: EC2 instance type string (e.g. "t4g.micro").
        allocated_storage_gb: Disk size in GB.
        expose_to: Service names that receive DB connection env vars.
        engine_version: PostgreSQL major version.
        backup_retention_days: Number of days to keep automated backups.
    """

    database_name: str
    expose_to: list[str] = field(default_factory=list)
    instance_type: str = "t4g.micro"
    allocated_storage_gb: int = 20
    engine_version: str = "15"
    backup_retention_days: int = 7


@dataclass
class UlimitConfig:
    """A Linux ulimit to set on the container.

    Attributes:
        name: Ulimit name (e.g. "nofile", "memlock").
        soft_limit: Soft limit value.
        hard_limit: Hard limit value.
    """

    name: str
    soft_limit: int
    hard_limit: int


@dataclass
class EbsVolumeConfig:
    """An EBS volume to attach to an EC2-backed ECS task.

    Attributes:
        name: Logical volume name used for tagging and snapshot discovery.
        size_gb: Volume size in GiB.
        mount_path: Container filesystem mount path (e.g. "/data").
        device_name: Linux block device name (e.g. "/dev/xvdf").
        volume_type: EBS volume type.
        filesystem_type: Filesystem to format the volume with (e.g. "ext4", "xfs").
    """

    name: str
    size_gb: int
    mount_path: str
    device_name: str = "/dev/xvdf"
    volume_type: str = "gp3"
    filesystem_type: str = "ext4"


@dataclass
class AlbPathRule:
    """Optional host+path listener rule targeting a service."""

    name: str
    path_pattern: str
    target_service: str
    priority: int


@dataclass
class AlbConfig:
    """Application Load Balancer configuration.

    Attributes:
        mode: "shared" looks up an existing ALB by name.
              "dedicated" provisions a new ALB for this project.
        shared_alb_name: The name of the existing shared ALB to look up.
        certificate_arn: ACM certificate ARN (required for dedicated mode).
    """

    mode: AlbMode = AlbMode.SHARED
    shared_alb_name: str = ""
    shared_listener_arn: str | None = None
    shared_alb_security_group_id: str | None = None
    certificate_arn: str | None = None
    domain: str | None = None
    default_target_service: str | None = None
    default_listener_priority: int | None = None
    path_rules: list[AlbPathRule] = field(default_factory=list)


@dataclass
class ServiceConfig:
    """A single ECS service (container), running on Fargate or EC2.

    Attributes:
        name: Logical service name (e.g. "django", "celery-worker").
        dockerfile: Path to the Dockerfile, relative to project root.
        build_context: Docker build context path, relative to project root.
        image: External container image URI (e.g. "docker.elastic.co/...:8.12.0").
            When set, ECR repo creation and Docker build/push are skipped.
        port: Container port exposed to the ALB. None for background workers.
        health_check_path: ALB health check endpoint.
        health_check_http_codes: ALB success HTTP code matcher (e.g. "200-399", "200-401").
        health_check_timeout_seconds: ALB health check timeout in seconds.
        health_check_interval_seconds: ALB health check interval in seconds.
        healthy_threshold_count: ALB healthy threshold count.
        unhealthy_threshold_count: ALB unhealthy threshold count.
        health_check_grace_period_seconds: ECS service grace period before health checks count.
        cpu: Task CPU units. Fargate supports 256-4096; EC2 is unconstrained.
        memory_mib: Task memory in MiB.
        desired_count: Number of running tasks.
        command: Override the container CMD.
        secrets: Names of ``SecretConfig`` entries to inject into this container.
        s3_access: Names of ``S3BucketConfig`` entries to grant read/write.
        environment_variables: Static env vars passed to the container.
        ulimits: Linux ulimits to set on the container (e.g. nofile).
        enable_exec: Enable ECS Exec for interactive shell access.
        launch_type: ECS launch type — "fargate" or "ec2".
        ec2_instance_type: EC2 instance type (required when launch_type is "ec2").
        architecture: CPU architecture — "x86_64" or "arm64". Auto-detected from
            ec2_instance_type when omitted.
        user_data_script: Path to a shell script for EC2 user data (optional).
        user_data_script_content: Inline EC2 user data shell script content.
        ebs_volumes: EBS volumes to attach (EC2 launch type only).
        enable_service_discovery: Register with Cloud Map for inter-service DNS
            discovery (``<service-name>.local``).
    """

    name: str
    dockerfile: str = "Dockerfile"
    build_context: str = "."
    image: str | None = None
    port: int | None = 8000
    health_check_path: str = "/health"
    health_check_http_codes: str = "200-399"
    health_check_timeout_seconds: int = 5
    health_check_interval_seconds: int = 30
    healthy_threshold_count: int = 5
    unhealthy_threshold_count: int = 2
    health_check_grace_period_seconds: int | None = None
    cpu: int = 256
    memory_mib: int = 512
    desired_count: int = 1
    command: str | None = None
    secrets: list[str] = field(default_factory=list)
    s3_access: list[str] = field(default_factory=list)
    environment_variables: dict[str, str] = field(default_factory=dict)
    ulimits: list[UlimitConfig] = field(default_factory=list)
    enable_exec: bool = True
    launch_type: LaunchType = LaunchType.FARGATE
    ec2_instance_type: str | None = None
    architecture: Architecture | None = None
    user_data_script: str | None = None
    user_data_script_content: str | None = None
    ebs_volumes: list[EbsVolumeConfig] = field(default_factory=list)
    enable_service_discovery: bool = False


@dataclass
class EnvironmentOverride:
    """Per-environment overrides for service-level settings.

    Any field set to None inherits from the service default.
    """

    instance_type_override: str | None = None
    """Override RDS instance type for this environment."""

    ec2_instance_type_override: dict[str, str] = field(default_factory=dict)
    """Map of service name -> EC2 instance type override for this environment."""


@dataclass
class ProjectConfig:
    """Top-level project configuration. Written to / read from ``darth-infra.toml``.

    Attributes:
        project_name: Short kebab-case project name (e.g. "my-webapp").
        aws_region: AWS region for deployment.
        vpc_name: Name tag of the existing VPC to deploy into.
        services: One or more ECS services to deploy.
        environments: Environment names. "prod" must be first.
        rds: Optional RDS database configuration.
        s3_buckets: Optional S3 buckets to provision per environment.
        alb: ALB configuration.
        secrets: Additional secrets to inject into containers.
        environment_overrides: Per-environment configuration overrides.
        tags: Additional tags applied to all resources.
    """

    project_name: str
    services: list[ServiceConfig]
    environments: list[str] = field(default_factory=lambda: ["prod"])
    aws_region: str = "us-east-1"
    vpc_name: str = "artshumrc-prod-standard"
    vpc_id: str | None = None
    private_subnet_ids: list[str] = field(default_factory=list)
    public_subnet_ids: list[str] = field(default_factory=list)
    rds: RdsConfig | None = None
    s3_buckets: list[S3BucketConfig] = field(default_factory=list)
    alb: AlbConfig = field(default_factory=AlbConfig)
    secrets: list[SecretConfig] = field(default_factory=list)
    environment_overrides: dict[str, EnvironmentOverride] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "prod" not in self.environments:
            raise ValueError("'prod' must be in the environments list")
        if self.environments[0] != "prod":
            self.environments.remove("prod")
            self.environments.insert(0, "prod")

        service_names = [s.name for s in self.services]
        service_ports = {s.name: s.port for s in self.services}
        if len(service_names) != len(set(service_names)):
            raise ValueError("Service names must be unique")

        for svc in self.services:
            if svc.launch_type == LaunchType.EC2 and not svc.ec2_instance_type:
                raise ValueError(
                    f"Service '{svc.name}' uses EC2 launch type "
                    f"but has no ec2_instance_type configured"
                )
            if svc.launch_type == LaunchType.FARGATE and svc.ebs_volumes:
                raise ValueError(
                    f"Service '{svc.name}' uses Fargate launch type "
                    f"but has ebs_volumes configured (EBS is EC2-only)"
                )

            # Auto-detect architecture from instance type when not set
            if (
                svc.launch_type == LaunchType.EC2
                and svc.ec2_instance_type
                and svc.architecture is None
            ):
                svc.architecture = detect_architecture(svc.ec2_instance_type)

        bucket_names = [b.name for b in self.s3_buckets]
        if len(bucket_names) != len(set(bucket_names)):
            raise ValueError("S3 bucket names must be unique")

        if self.rds:
            for svc_name in self.rds.expose_to:
                if svc_name not in service_names:
                    raise ValueError(
                        f"RDS expose_to references unknown service '{svc_name}'"
                    )

        for secret in self.secrets:
            if secret.source == SecretSource.GENERATE and not secret.generate_once:
                raise ValueError(
                    f"Secret '{secret.name}' sets generate_once=false, "
                    "which is not supported"
                )

        for svc in self.services:
            for s3_name in svc.s3_access:
                if s3_name not in bucket_names:
                    raise ValueError(
                        f"Service '{svc.name}' references unknown S3 bucket '{s3_name}'"
                    )
            secret_names = [s.name for s in self.secrets]
            for sec_name in svc.secrets:
                if sec_name not in secret_names:
                    raise ValueError(
                        f"Service '{svc.name}' references unknown secret '{sec_name}'"
                    )

        if self.alb.domain:
            if not self.alb.default_target_service:
                raise ValueError(
                    "alb.default_target_service is required when alb.domain is set"
                )
            if self.alb.default_target_service not in service_ports:
                raise ValueError(
                    f"alb.default_target_service references unknown service "
                    f"'{self.alb.default_target_service}'"
                )
            if service_ports[self.alb.default_target_service] is None:
                raise ValueError(
                    f"alb.default_target_service '{self.alb.default_target_service}' "
                    "must target a service with a container port"
                )
            if self.alb.default_listener_priority is None:
                raise ValueError(
                    "alb.default_listener_priority is required when alb.domain is set"
                )

        if self.alb.default_listener_priority is not None and not (
            1 <= self.alb.default_listener_priority <= 50000
        ):
            raise ValueError("alb.default_listener_priority must be between 1 and 50000")

        seen_rule_names: set[str] = set()
        seen_rule_param_suffixes: set[str] = set()
        seen_priorities: set[int] = set()
        if self.alb.default_listener_priority is not None:
            seen_priorities.add(self.alb.default_listener_priority)
        for rule in self.alb.path_rules:
            if rule.name in seen_rule_names:
                raise ValueError(f"Duplicate alb.path_rules name '{rule.name}'")
            seen_rule_names.add(rule.name)
            suffix = _rule_param_suffix(rule.name)
            if suffix in seen_rule_param_suffixes:
                raise ValueError(
                    f"alb.path_rules names must map to unique parameter keys; "
                    f"'{rule.name}' collides after normalization"
                )
            seen_rule_param_suffixes.add(suffix)

            if rule.target_service not in service_ports:
                raise ValueError(
                    f"alb.path_rules '{rule.name}' references unknown service "
                    f"'{rule.target_service}'"
                )
            if service_ports[rule.target_service] is None:
                raise ValueError(
                    f"alb.path_rules '{rule.name}' target '{rule.target_service}' "
                    "must have a container port"
                )
            if not (1 <= rule.priority <= 50000):
                raise ValueError(
                    f"alb.path_rules '{rule.name}' priority must be between 1 and 50000"
                )
            if rule.priority in seen_priorities:
                raise ValueError(
                    f"Duplicate ALB listener priority '{rule.priority}' in routing rules"
                )
            seen_priorities.add(rule.priority)

        if self.alb.default_target_service and not self.alb.domain:
            raise ValueError("alb.domain is required when alb.default_target_service is set")
        if self.alb.default_listener_priority is not None and not self.alb.domain:
            raise ValueError("alb.domain is required when alb.default_listener_priority is set")
        if self.alb.path_rules and not self.alb.domain:
            raise ValueError("alb.domain is required when alb.path_rules are configured")

    def get_cluster_domain(self, env: str) -> str | None:
        """Resolve cluster host domain for a given environment."""
        if not self.alb.domain:
            return None
        if env == "prod":
            return self.alb.domain
        return f"{env}.{self.alb.domain}"

    def get_rds_instance_type(self, env: str) -> str:
        """Resolve the RDS instance type for a given environment."""
        if self.rds is None:
            raise ValueError("No RDS configured")

        overrides = self.environment_overrides.get(env)
        if overrides and overrides.instance_type_override:
            return overrides.instance_type_override

        return self.rds.instance_type
