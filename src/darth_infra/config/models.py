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
    certificate_arn: str | None = None


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
        cpu: Task CPU units. Fargate supports 256-4096; EC2 is unconstrained.
        memory_mib: Task memory in MiB.
        desired_count: Number of running tasks.
        command: Override the container CMD.
        domain: Hostname for ALB host-header routing. When port is set but domain
            is omitted the service is internal-only (no ALB target).
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
    cpu: int = 256
    memory_mib: int = 512
    desired_count: int = 1
    command: str | None = None
    domain: str | None = None
    secrets: list[str] = field(default_factory=list)
    s3_access: list[str] = field(default_factory=list)
    environment_variables: dict[str, str] = field(default_factory=dict)
    ulimits: list[UlimitConfig] = field(default_factory=list)
    enable_exec: bool = True
    launch_type: LaunchType = LaunchType.FARGATE
    ec2_instance_type: str | None = None
    architecture: Architecture | None = None
    user_data_script: str | None = None
    ebs_volumes: list[EbsVolumeConfig] = field(default_factory=list)
    enable_service_discovery: bool = False


@dataclass
class EnvironmentOverride:
    """Per-environment overrides for service-level settings.

    Any field set to None inherits from the service default.
    """

    domain_overrides: dict[str, str] = field(default_factory=dict)
    """Map of service name -> domain override for this environment."""

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

    def get_domain_for_service(self, service_name: str, env: str) -> str | None:
        """Resolve the domain for a service in a given environment."""
        svc = next((s for s in self.services if s.name == service_name), None)
        if svc is None or svc.domain is None:
            return None

        overrides = self.environment_overrides.get(env)
        if overrides and service_name in overrides.domain_overrides:
            return overrides.domain_overrides[service_name]

        if env == "prod":
            return svc.domain

        return f"{env}-{svc.domain}"

    def get_rds_instance_type(self, env: str) -> str:
        """Resolve the RDS instance type for a given environment."""
        if self.rds is None:
            raise ValueError("No RDS configured")

        overrides = self.environment_overrides.get(env)
        if overrides and overrides.instance_type_override:
            return overrides.instance_type_override

        return self.rds.instance_type
