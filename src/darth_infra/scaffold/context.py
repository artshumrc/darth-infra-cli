"""Typed derivation layer for CloudFormation template generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

from ..config.models import (
    AlbConfig,
    ProjectConfig,
    RdsConfig,
    S3BucketMode,
    SecretSource,
    ServiceConfig,
    TagParameter,
)


@dataclass(frozen=True)
class SecretRenderContext:
    name: str
    source: SecretSource
    existing_secret_name: str | None
    length: int
    generate_once: bool
    logical_id_fragment: str
    generated_secret_logical_id: str
    external_parameter_name: str


@dataclass(frozen=True)
class SecretParameterContext:
    secret_name: str
    param_name: str
    source: str
    requires_param: bool
    rds_json_key: str | None


@dataclass(frozen=True)
class EbsVolumeRenderContext:
    name: str
    name_pascal: str
    size_gb: int
    mount_path: str
    device_name: str
    filesystem_type: str
    volume_type: str


@dataclass(frozen=True)
class S3AccessRenderContext:
    bucket_name: str
    bucket_ref: str | None
    bucket_name_literal: str | None
    env_key: str
    param_name: str
    arn_param_name: str
    fallback_param_name: str | None
    fallback_arn_param_name: str | None
    fallback_bucket_name_literal: str | None
    fallback_env_key: str | None
    cf_param_name: str | None
    cloudfront_env_key: str | None
    read_only: bool


@dataclass(frozen=True)
class CloudFrontAccessRenderContext:
    env_key: str
    param_name: str


@dataclass(frozen=True)
class AlbPathRuleRenderContext:
    name: str
    name_pascal: str
    path_pattern: str
    priority: int | None
    priority_param_name: str


@dataclass(frozen=True)
class ListenerHostnameContext:
    is_ref: bool
    ref_name: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class ServiceRenderContext:
    name: str
    name_pascal: str
    svc: ServiceConfig
    has_alb_target: bool
    launch_type: str
    architecture: str | None
    user_data_script_content: str | None
    has_rds: bool
    s3_vars: tuple[S3AccessRenderContext, ...]
    cloudfront_vars: tuple[CloudFrontAccessRenderContext, ...]
    secret_params: tuple[SecretParameterContext, ...]
    ebs_params: tuple[EbsVolumeRenderContext, ...]
    default_listener_priority: int | None
    default_listener_priority_param_name: str
    is_default_listener_target: bool
    service_path_rules: tuple[AlbPathRuleRenderContext, ...]
    listener_hostnames: tuple[ListenerHostnameContext, ...]
    has_cluster_routing_rules: bool


@dataclass(frozen=True)
class S3BucketRenderContext:
    name: str
    mode: S3BucketMode
    existing_bucket_name: str | None
    seed_source_bucket_name: str | None
    preview_fallback_bucket_name: str | None
    preview_fallback_env_key: str | None
    seed_non_prod_only: bool
    public_read: bool
    cloudfront: bool
    cors: bool
    provision_bucket: bool
    logical_id_fragment: str
    bucket_logical_id: str
    cloudfront_oac_logical_id: str
    cloudfront_logical_id: str
    bucket_policy_logical_id: str


@dataclass(frozen=True)
class CloudFrontCachedBehaviorRenderContext:
    name: str
    name_pascal: str
    path_pattern: str
    compress: bool
    cache_by_origin_headers: bool
    min_ttl_seconds: int
    default_ttl_seconds: int
    max_ttl_seconds: int
    query_strings: str
    query_string_allowlist: tuple[str, ...]
    cookies: str
    cookie_allowlist: tuple[str, ...]
    origin_request_headers: tuple[str, ...]
    forward_authorization_header: bool


@dataclass(frozen=True)
class AlbCloudFrontRenderContext:
    origin_https_only: bool
    custom_domain: str | None
    certificate_arn: str | None
    price_class: str
    comment: str | None
    cached_behaviors: tuple[CloudFrontCachedBehaviorRenderContext, ...]


@dataclass(frozen=True)
class RenderContext:
    project_name: str
    project_name_pascal: str
    aws_region: str
    vpc_name: str
    vpc_id: str | None
    private_subnet_ids: tuple[str, ...]
    public_subnet_ids: tuple[str, ...]
    services: tuple[ServiceConfig, ...]
    services_ctx: tuple[ServiceRenderContext, ...]
    environments: tuple[str, ...]
    has_rds: bool
    has_s3: bool
    has_cloudfront: bool
    has_alb_cloudfront: bool
    has_cluster_routing: bool
    alb_path_rules_ctx: tuple[AlbPathRuleRenderContext, ...]
    alb_cloudfront: AlbCloudFrontRenderContext
    has_ec2: bool
    has_service_discovery: bool
    service_discovery_namespace_cfn: str
    rds: RdsConfig | None
    rds_master_username: str
    s3_buckets: tuple[S3BucketRenderContext, ...]
    alb: AlbConfig
    secrets: tuple[SecretRenderContext, ...]
    tag_parameters: tuple[TagParameter, ...]
    tags: dict[str, str]


def _pascalize(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _resolve_user_data_script_content(
    inline: str | None, path: str | None
) -> str | None:
    content = (inline or "").strip()
    if not content and path:
        src_script = Path.cwd() / path
        if src_script.is_file():
            content = src_script.read_text().strip()
    if not content:
        return None
    return content.replace("${", r"\${!")


def _derive_rds_master_username(database_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", database_name)
    if not normalized:
        normalized = "appuser"
    if not normalized[0].isalpha():
        normalized = f"u{normalized}"
    return normalized[:16].lower()


def _normalize_rds_json_key(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw in {"host", "port", "dbname", "username", "password"}:
        return raw

    lowered = raw.lower().strip()
    if lowered.startswith("rds"):
        lowered = lowered[3:].strip()
    compact = "".join(character for character in lowered if character.isalnum())
    aliases = {
        "host": "host",
        "port": "port",
        "dbname": "dbname",
        "database": "dbname",
        "databasename": "dbname",
        "db": "dbname",
        "user": "username",
        "username": "username",
        "pass": "password",
        "password": "password",
    }
    return aliases.get(compact, raw)


def _secret_logical_id_fragment(name: str) -> str:
    return name.replace("_", "").replace("-", "")


def _bucket_logical_id_fragment(name: str) -> str:
    return name.replace("-", "")


def derive_render_context(config: ProjectConfig) -> RenderContext:
    """Derive all template-facing values from a project configuration."""
    routed_alb_target_services: set[str] = set()
    if config.alb.domain:
        if config.alb.default_target_service:
            routed_alb_target_services.add(config.alb.default_target_service)
        routed_alb_target_services.update(
            rule.target_service for rule in config.alb.path_rules
        )

    rds_expose_to = set(config.rds.expose_to if config.rds else ())
    rds_secret_key_by_env = {
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
    required_postgres_secret_names = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    )
    secrets_by_name = {secret.name: secret for secret in config.secrets}

    s3_access_by_service: dict[str, list[S3AccessRenderContext]] = {}
    s3_buckets: list[S3BucketRenderContext] = []
    seen_s3_entries_by_service: dict[
        str, set[tuple[str, str, str | None, bool]]
    ] = {}
    for bucket in config.s3_buckets:
        uses_preview_overlay = bool(
            config.active_preview and bucket.preview_fallback_bucket_name
        )
        provisions_managed_bucket = (
            bucket.mode.value != "existing" or uses_preview_overlay
        )
        logical_id_fragment = _bucket_logical_id_fragment(bucket.name)
        bucket_logical_id = f"Bucket{logical_id_fragment}"
        s3_buckets.append(
            S3BucketRenderContext(
                name=bucket.name,
                mode=bucket.mode,
                existing_bucket_name=bucket.existing_bucket_name,
                seed_source_bucket_name=bucket.seed_source_bucket_name,
                preview_fallback_bucket_name=bucket.preview_fallback_bucket_name,
                preview_fallback_env_key=bucket.preview_fallback_env_key,
                seed_non_prod_only=bucket.seed_non_prod_only,
                public_read=bucket.public_read,
                cloudfront=bucket.cloudfront,
                cors=bucket.cors,
                provision_bucket=provisions_managed_bucket,
                logical_id_fragment=logical_id_fragment,
                bucket_logical_id=bucket_logical_id,
                cloudfront_oac_logical_id=f"CloudFrontOac{logical_id_fragment}",
                cloudfront_logical_id=f"CloudFront{logical_id_fragment}",
                bucket_policy_logical_id=f"BucketPolicy{logical_id_fragment}",
            )
        )
        bucket_ref = bucket_logical_id if provisions_managed_bucket else None
        bucket_name_literal = (
            bucket.existing_bucket_name if not provisions_managed_bucket else None
        )
        fallback_bucket_name_literal = (
            bucket.preview_fallback_bucket_name
            if config.active_preview and bucket.preview_fallback_bucket_name
            else None
        )
        for connection in bucket.connections:
            dedupe_key = (
                bucket.name,
                connection.env_key,
                connection.cloudfront_env_key,
                connection.read_only,
            )
            seen_for_service = seen_s3_entries_by_service.setdefault(
                connection.service, set()
            )
            if dedupe_key in seen_for_service:
                continue
            seen_for_service.add(dedupe_key)
            bucket_name_pascal = _pascalize(bucket.name)
            s3_access_by_service.setdefault(connection.service, []).append(
                S3AccessRenderContext(
                    bucket_name=bucket.name,
                    bucket_ref=bucket_ref,
                    bucket_name_literal=bucket_name_literal,
                    env_key=connection.env_key,
                    param_name=f"BucketName{bucket_name_pascal}",
                    arn_param_name=f"BucketArn{bucket_name_pascal}",
                    fallback_param_name=(
                        f"FallbackBucketName{bucket_name_pascal}"
                        if fallback_bucket_name_literal
                        else None
                    ),
                    fallback_arn_param_name=(
                        f"FallbackBucketArn{bucket_name_pascal}"
                        if fallback_bucket_name_literal
                        else None
                    ),
                    fallback_bucket_name_literal=fallback_bucket_name_literal,
                    fallback_env_key=(
                        bucket.preview_fallback_env_key
                        if fallback_bucket_name_literal
                        else None
                    ),
                    cf_param_name=(
                        f"CloudFrontUrl{bucket_name_pascal}"
                        if bucket.cloudfront
                        and connection.cloudfront_env_key
                        and provisions_managed_bucket
                        else None
                    ),
                    cloudfront_env_key=(
                        connection.cloudfront_env_key if bucket.cloudfront else None
                    ),
                    read_only=connection.read_only,
                )
            )

    for service_name, entries in s3_access_by_service.items():
        s3_access_by_service[service_name] = sorted(
            entries,
            key=lambda item: (
                item.bucket_name,
                item.env_key,
                item.cloudfront_env_key or "",
            ),
        )

    cloudfront_access_by_service: dict[
        str, list[CloudFrontAccessRenderContext]
    ] = {}
    for connection in config.cloudfront.connections:
        cloudfront_access_by_service.setdefault(connection.service, []).append(
            CloudFrontAccessRenderContext(
                env_key=connection.env_key,
                param_name=f"CloudFrontUrl{_pascalize(connection.env_key)}",
            )
        )
    for service_name, entries in cloudfront_access_by_service.items():
        seen_param_names: set[str] = set()
        deduped: list[CloudFrontAccessRenderContext] = []
        for entry in entries:
            if entry.param_name in seen_param_names:
                continue
            seen_param_names.add(entry.param_name)
            deduped.append(entry)
        cloudfront_access_by_service[service_name] = sorted(
            deduped, key=lambda item: item.env_key
        )

    services: list[ServiceRenderContext] = []
    alb_target_service_names: set[str] = set()
    for service in config.services:
        has_alb_target = (
            service.port is not None and service.name in routed_alb_target_services
        )
        name_pascal = _pascalize(service.name)
        secret_params: list[SecretParameterContext] = []
        service_has_rds_secret = False
        for secret_name in service.secrets:
            secret_config = secrets_by_name.get(secret_name)
            source = _enum_value(secret_config.source) if secret_config else "generate"
            rds_key = None
            if source == "rds":
                rds_key = _normalize_rds_json_key(
                    str(secret_config.existing_secret_name).strip()
                    if secret_config and secret_config.existing_secret_name
                    else rds_secret_key_by_env.get(secret_name)
                )
                service_has_rds_secret = True
            secret_params.append(
                SecretParameterContext(
                    secret_name=secret_name,
                    param_name=(
                        f"SecretArn{_secret_logical_id_fragment(secret_name)}"
                    ),
                    source=source,
                    requires_param=source != "rds",
                    rds_json_key=rds_key,
                )
            )

        if config.rds and service.name in rds_expose_to:
            present_secret_names = {param.secret_name for param in secret_params}
            for secret_name in required_postgres_secret_names:
                if secret_name in present_secret_names:
                    continue
                secret_params.append(
                    SecretParameterContext(
                        secret_name=secret_name,
                        param_name=(
                            f"SecretArn{_secret_logical_id_fragment(secret_name)}"
                        ),
                        source="rds",
                        requires_param=False,
                        rds_json_key=rds_secret_key_by_env[secret_name],
                    )
                )

        if has_alb_target:
            alb_target_service_names.add(service.name)
        services.append(
            ServiceRenderContext(
                name=service.name,
                name_pascal=name_pascal,
                svc=service,
                has_alb_target=has_alb_target,
                launch_type=_enum_value(service.launch_type),
                architecture=(
                    _enum_value(service.architecture)
                    if service.architecture is not None
                    else None
                ),
                user_data_script_content=_resolve_user_data_script_content(
                    service.user_data_script_content,
                    service.user_data_script,
                ),
                has_rds=bool(config.rds)
                and (
                    service.name in rds_expose_to
                    or service_has_rds_secret
                ),
                s3_vars=tuple(s3_access_by_service.get(service.name, ())),
                cloudfront_vars=tuple(
                    cloudfront_access_by_service.get(service.name, ())
                ),
                secret_params=tuple(secret_params),
                ebs_params=tuple(
                    EbsVolumeRenderContext(
                        name=volume.name,
                        name_pascal=_pascalize(volume.name),
                        size_gb=volume.size_gb,
                        mount_path=volume.mount_path,
                        device_name=volume.device_name,
                        filesystem_type=volume.filesystem_type,
                        volume_type=volume.volume_type,
                    )
                    for volume in service.ebs_volumes
                ),
                default_listener_priority=config.alb.default_listener_priority,
                default_listener_priority_param_name="DefaultListenerPriority",
                is_default_listener_target=False,
                service_path_rules=(),
                listener_hostnames=(),
                has_cluster_routing_rules=False,
            )
        )

    path_rules_by_service: dict[str, list[AlbPathRuleRenderContext]] = {}
    alb_path_rules: list[AlbPathRuleRenderContext] = []
    for rule in config.alb.path_rules:
        if rule.target_service not in alb_target_service_names:
            continue
        rule_context = AlbPathRuleRenderContext(
            name=rule.name,
            name_pascal=_pascalize(rule.name),
            path_pattern=rule.path_pattern,
            priority=rule.priority,
            priority_param_name=f"PathRulePriority{_pascalize(rule.name)}",
        )
        alb_path_rules.append(rule_context)
        path_rules_by_service.setdefault(rule.target_service, []).append(rule_context)

    for index, service_context in enumerate(services):
        service_path_rules = tuple(
            path_rules_by_service.get(service_context.name, ())
        )
        is_default_listener_target = bool(
            config.alb.domain
            and config.alb.default_target_service == service_context.name
            and service_context.has_alb_target
        )
        listener_hostnames: list[ListenerHostnameContext] = []
        if config.alb.domain:
            listener_hostnames.append(
                ListenerHostnameContext(is_ref=True, ref_name="ClusterDomain")
            )
            cloudfront_custom_domain = (config.cloudfront.custom_domain or "").strip()
            if (
                cloudfront_custom_domain
                and cloudfront_custom_domain != config.alb.domain
            ):
                listener_hostnames.append(
                    ListenerHostnameContext(
                        is_ref=False,
                        value=cloudfront_custom_domain,
                    )
                )
        services[index] = replace(
            service_context,
            is_default_listener_target=is_default_listener_target,
            service_path_rules=service_path_rules,
            listener_hostnames=tuple(listener_hostnames),
            has_cluster_routing_rules=bool(
                config.alb.domain
                and (is_default_listener_target or service_path_rules)
            ),
        )

    secret_contexts = []
    for secret in config.secrets:
        logical_id_fragment = _secret_logical_id_fragment(secret.name)
        secret_contexts.append(
            SecretRenderContext(
                name=secret.name,
                source=secret.source,
                existing_secret_name=secret.existing_secret_name,
                length=secret.length,
                generate_once=secret.generate_once,
                logical_id_fragment=logical_id_fragment,
                generated_secret_logical_id=f"Secret{logical_id_fragment}",
                external_parameter_name=f"EnvSecretArn{logical_id_fragment}",
            )
        )

    cloudfront = config.cloudfront
    return RenderContext(
        project_name=config.project_name,
        project_name_pascal=_pascalize(config.project_name),
        aws_region=config.aws_region,
        vpc_name=config.vpc_name,
        vpc_id=config.vpc_id,
        private_subnet_ids=tuple(config.private_subnet_ids),
        public_subnet_ids=tuple(config.public_subnet_ids),
        services=tuple(config.services),
        services_ctx=tuple(services),
        environments=tuple(config.environments),
        has_rds=config.rds is not None,
        has_s3=bool(config.s3_buckets),
        has_cloudfront=any(
            bucket.cloudfront and bucket.mode.value != "existing"
            for bucket in config.s3_buckets
        ),
        has_alb_cloudfront=cloudfront.enabled,
        has_cluster_routing=bool(
            config.alb.domain
            and (config.alb.default_target_service or config.alb.path_rules)
        ),
        alb_path_rules_ctx=tuple(alb_path_rules),
        alb_cloudfront=AlbCloudFrontRenderContext(
            origin_https_only=cloudfront.origin_https_only,
            custom_domain=cloudfront.custom_domain,
            certificate_arn=cloudfront.certificate_arn,
            price_class=cloudfront.price_class,
            comment=cloudfront.comment,
            cached_behaviors=tuple(
                CloudFrontCachedBehaviorRenderContext(
                    name=behavior.name,
                    name_pascal=_pascalize(behavior.name),
                    path_pattern=behavior.path_pattern,
                    compress=behavior.compress,
                    cache_by_origin_headers=behavior.cache_by_origin_headers,
                    min_ttl_seconds=behavior.min_ttl_seconds,
                    default_ttl_seconds=behavior.default_ttl_seconds,
                    max_ttl_seconds=behavior.max_ttl_seconds,
                    query_strings=_enum_value(behavior.query_strings),
                    query_string_allowlist=tuple(behavior.query_string_allowlist),
                    cookies=_enum_value(behavior.cookies),
                    cookie_allowlist=tuple(behavior.cookie_allowlist),
                    origin_request_headers=tuple(behavior.origin_request_headers),
                    forward_authorization_header=(
                        behavior.forward_authorization_header
                    ),
                )
                for behavior in cloudfront.cached_behaviors
            ),
        ),
        has_ec2=any(
            _enum_value(service.launch_type) == "ec2" for service in config.services
        ),
        has_service_discovery=any(
            service.enable_service_discovery for service in config.services
        ),
        service_discovery_namespace_cfn=(
            config.get_service_discovery_namespace_cfn()
        ),
        rds=config.rds,
        rds_master_username=(
            _derive_rds_master_username(config.rds.database_name)
            if config.rds is not None
            else ""
        ),
        s3_buckets=tuple(s3_buckets),
        alb=config.alb,
        secrets=tuple(secret_contexts),
        tag_parameters=tuple(config.get_tag_parameters()),
        tags=dict(config.tags),
    )
