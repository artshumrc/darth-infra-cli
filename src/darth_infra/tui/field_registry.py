"""Machine-readable field registry and schema-coverage contract for the editor.

The persisted configuration schema (``darth-infra.schema.json``) is the
completeness boundary for the Guided editor: every user-authored field must be
editable somewhere in the TUI. This module makes that contract mechanical.

Two halves live here:

* :func:`enumerate_schema_paths` walks a JSON Schema document and returns the set
  of *editable* value paths (leaves plus editable map/list containers) and the
  set of *read-only* paths. It handles nested objects, arrays of objects, maps
  with arbitrary keys, nullable values, and fields marked ``"readOnly": true``.
* :data:`FIELD_REGISTRY` assigns every editable path a canonical editor section,
  common-versus-Advanced placement, an intended control kind, and TUI help/
  example metadata. Core meaning, defaults, ranges, and constraints continue to
  come from the schema itself; the registry only adds presentation intent.

The registry describes purpose-built controls. It does not generate a generic
editor directly from JSON Schema.

Path notation uses one stable wildcard convention:

* ``[]`` for each item of an array of objects, e.g. ``services[].name``.
* ``.*`` for the values of a map with arbitrary keys, e.g.
  ``services[].environment_variables.*`` and ``environments.*.tags.*``.

Runtime-only state (for example the resolved active preview environment) is not
part of the persisted schema and is therefore absent here by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

# Re-exported: the schema document is owned by the config layer, but callers of
# the registry have always reached it through here.
from ..config.schema import SCHEMA_PATH as SCHEMA_PATH, load_schema as load_schema


class Section(str, Enum):
    """The nine canonical editor sections."""

    PROJECT = "project"
    NETWORK = "network"
    SERVICES = "services"
    ROUTING = "routing"
    DATABASE = "database"
    STORAGE = "storage"
    SECRETS = "secrets"
    ENVIRONMENTS = "environments"
    REVIEW = "review"


class Placement(str, Enum):
    """Whether a field is shown immediately or under an Advanced panel."""

    COMMON = "common"
    ADVANCED = "advanced"


class Control(str, Enum):
    """The intended purpose-built control kind for a field.

    This describes editor intent only; validation and defaults come from the
    schema. It deliberately names a small set of purpose-built controls rather
    than mapping one-to-one onto raw JSON Schema types.
    """

    TEXT = "text"
    TEXTAREA = "textarea"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    SELECT = "select"
    STRING_LIST = "string_list"
    REFERENCE_LIST = "reference_list"
    SERVICE_SELECT = "service_select"
    KEY_VALUE_MAP = "key_value_map"


@dataclass(frozen=True)
class FieldEntry:
    """One registered editor control for a persisted schema path.

    Attributes:
        path: Canonical wildcard schema path (see module docstring for notation).
        section: The owning editor section.
        placement: Common (always visible) or Advanced (grouped/collapsible).
        control: Intended purpose-built control kind.
        help: Concise TUI help. Core meaning still comes from the schema
            description; this adds presentation-oriented guidance.
        example: Optional example value shown in expanded help.
    """

    path: str
    section: Section
    placement: Placement
    control: Control
    help: str
    example: str | None = None


@dataclass(frozen=True)
class SchemaFieldSet:
    """The classified paths discovered while walking a schema document."""

    editable: frozenset[str]
    read_only: frozenset[str]


def _types(subschema: dict[str, Any]) -> set[str]:
    """Return the JSON Schema declared types as a set (nullable-aware)."""
    declared = subschema.get("type")
    if declared is None:
        return set()
    if isinstance(declared, list):
        return set(declared)
    return {declared}


def _is_fixed_object(subschema: dict[str, Any]) -> bool:
    return "object" in _types(subschema) and bool(subschema.get("properties"))


def _walk(path: str, subschema: dict[str, Any], fields: _MutablePaths) -> None:
    """Classify ``subschema`` at ``path`` and recurse structurally.

    A field marked ``"readOnly": true`` is recorded as read-only and never
    descended into. Every other node is classified as one of:

    * fixed-property object -> structural, recurse per property;
    * map of objects (``additionalProperties`` is an object schema) ->
      structural, recurse into value properties under a ``.*`` key segment;
    * map of scalars -> one editable container entry at ``path.*``;
    * array of objects -> structural, recurse into item properties under ``[]``;
    * array of scalars -> one editable list container entry at ``path``;
    * scalar leaf -> one editable entry at ``path``.
    """
    if subschema.get("readOnly") is True:
        if path:
            fields.read_only.add(path)
        return

    types = _types(subschema)

    if "object" in types:
        properties = subschema.get("properties")
        if properties:
            for name, child in properties.items():
                # ``$``-prefixed names are reserved JSON Schema meta keywords
                # (e.g. the ``$schema`` self-pointer), not user config fields.
                if name.startswith("$"):
                    continue
                child_path = f"{path}.{name}" if path else name
                _walk(child_path, child, fields)
            return

        additional = subschema.get("additionalProperties")
        if isinstance(additional, dict):
            if _is_fixed_object(additional):
                # Map with arbitrary keys whose values are structured objects.
                for name, child in additional["properties"].items():
                    if name.startswith("$"):
                        continue
                    _walk(f"{path}.*.{name}", child, fields)
                return
            # Map with arbitrary keys whose values are scalars: one container.
            fields.editable.add(f"{path}.*")
            return

        # Object with neither fixed properties nor a value schema: nothing to
        # edit. No such node exists in the current schema.
        return

    if "array" in types:
        items = subschema.get("items", {})
        if _is_fixed_object(items):
            for name, child in items["properties"].items():
                if name.startswith("$"):
                    continue
                _walk(f"{path}[].{name}", child, fields)
            return
        # Array of scalars: one editable list container.
        if path:
            fields.editable.add(path)
        return

    # Scalar leaf (string / integer / number / boolean, possibly nullable/enum).
    if path:
        fields.editable.add(path)


@dataclass
class _MutablePaths:
    editable: set[str]
    read_only: set[str]


def enumerate_schema_paths(schema: dict[str, Any]) -> SchemaFieldSet:
    """Enumerate editable and read-only value paths in a JSON Schema document.

    Args:
        schema: A parsed JSON Schema object (draft-07 shape used by this project).

    Returns:
        A :class:`SchemaFieldSet` whose ``editable`` set is every path a user may
        edit and whose ``read_only`` set is every path explicitly marked
        ``"readOnly": true``.
    """
    fields = _MutablePaths(editable=set(), read_only=set())
    _walk("", schema, fields)
    return SchemaFieldSet(
        editable=frozenset(fields.editable),
        read_only=frozenset(fields.read_only),
    )


def registry_paths() -> set[str]:
    """Return the set of schema paths covered by the field registry."""
    return {entry.path for entry in FIELD_REGISTRY}


def registry_entry(path: str) -> FieldEntry | None:
    """Return the registry entry for ``path`` if one exists."""
    return _REGISTRY_BY_PATH.get(path)


def uncovered_editable_paths(
    schema: dict[str, Any], covered: set[str] | None = None
) -> set[str]:
    """Return editable schema paths that lack a registry entry.

    A field is uncovered only if it is editable (not explicitly read-only) and
    has no registered control. Read-only fields are permitted to be absent.

    Args:
        schema: A parsed JSON Schema object.
        covered: Path set to compare against; defaults to the field registry.
    """
    if covered is None:
        covered = registry_paths()
    return set(enumerate_schema_paths(schema).editable) - set(covered)


# ---------------------------------------------------------------------------
# The registry.
#
# One entry per editable leaf or editable map/list container in the persisted
# schema. Kept grouped by section for readability. cli_version_floor is
# deliberately absent: it is CLI-maintained metadata marked read-only in the
# schema and displayed for inspection only.
# ---------------------------------------------------------------------------

_S = Section
_P = Placement
_C = Control


FIELD_REGISTRY: tuple[FieldEntry, ...] = (
    # -- Project -----------------------------------------------------------
    FieldEntry(
        "project.name", _S.PROJECT, _P.COMMON, _C.TEXT,
        "Short project name used as a prefix for all AWS resources.",
        example="my-webapp",
    ),
    FieldEntry(
        "project.aws_region", _S.PROJECT, _P.COMMON, _C.TEXT,
        "AWS region every environment deploys into.",
        example="us-east-1",
    ),
    FieldEntry(
        "project.tags.*", _S.PROJECT, _P.ADVANCED, _C.KEY_VALUE_MAP,
        "Extra tags applied to all AWS resources.",
        example="team = platform",
    ),
    # -- Network -----------------------------------------------------------
    FieldEntry(
        "project.vpc_name", _S.NETWORK, _P.COMMON, _C.TEXT,
        "Name tag of the existing VPC to deploy into.",
        example="artshumrc-prod-standard",
    ),
    FieldEntry(
        "project.vpc_id", _S.NETWORK, _P.ADVANCED, _C.TEXT,
        "Explicit VPC ID; overrides vpc_name lookup when set.",
        example="vpc-0abc1234def567890",
    ),
    FieldEntry(
        "project.private_subnet_ids", _S.NETWORK, _P.ADVANCED, _C.STRING_LIST,
        "Explicit private subnet IDs for ECS tasks and RDS; discovered when empty.",
        example="subnet-0aaa, subnet-0bbb",
    ),
    FieldEntry(
        "project.public_subnet_ids", _S.NETWORK, _P.ADVANCED, _C.STRING_LIST,
        "Explicit public subnet IDs for a dedicated ALB; discovered when empty.",
        example="subnet-0ccc, subnet-0ddd",
    ),
    # -- Services ----------------------------------------------------------
    FieldEntry(
        "service_discovery.namespace_template", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Cloud Map private DNS namespace template for inter-service discovery.",
        example="{project}-{env}.local",
    ),
    FieldEntry(
        "services[].name", _S.SERVICES, _P.COMMON, _C.TEXT,
        "Logical service name.",
        example="django",
    ),
    FieldEntry(
        "services[].image", _S.SERVICES, _P.COMMON, _C.TEXT,
        "External image URI; when set, Docker build/push is skipped.",
        example="redis:7-alpine",
    ),
    FieldEntry(
        "services[].dockerfile", _S.SERVICES, _P.COMMON, _C.TEXT,
        "Path to the Dockerfile relative to project root.",
    ),
    FieldEntry(
        "services[].build_context", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Docker build context path relative to project root.",
    ),
    FieldEntry(
        "services[].docker_build_target", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Optional Dockerfile build target stage.",
        example="runtime",
    ),
    FieldEntry(
        "services[].port", _S.SERVICES, _P.COMMON, _C.INTEGER,
        "Container port exposed to the ALB; leave empty for background workers.",
    ),
    FieldEntry(
        "services[].health_check_path", _S.SERVICES, _P.COMMON, _C.TEXT,
        "ALB health check endpoint.",
    ),
    FieldEntry(
        "services[].health_check_http_codes", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "ALB health check success HTTP code matcher.",
        example="200-399",
    ),
    FieldEntry(
        "services[].health_check_timeout_seconds", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "ALB health check timeout in seconds.",
    ),
    FieldEntry(
        "services[].health_check_interval_seconds", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "ALB health check interval in seconds.",
    ),
    FieldEntry(
        "services[].healthy_threshold_count", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "Consecutive successes required to mark a target healthy.",
    ),
    FieldEntry(
        "services[].unhealthy_threshold_count", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "Consecutive failures required to mark a target unhealthy.",
    ),
    FieldEntry(
        "services[].health_check_grace_period_seconds", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "Grace period before load balancer health checks are enforced.",
    ),
    FieldEntry(
        "services[].cpu", _S.SERVICES, _P.COMMON, _C.INTEGER,
        "Task CPU units.",
    ),
    FieldEntry(
        "services[].memory_mib", _S.SERVICES, _P.COMMON, _C.INTEGER,
        "Task memory in MiB.",
    ),
    FieldEntry(
        "services[].desired_count", _S.SERVICES, _P.COMMON, _C.INTEGER,
        "Number of running tasks.",
    ),
    FieldEntry(
        "services[].command", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Override the container CMD.",
    ),
    FieldEntry(
        "services[].entrypoint", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Override the image ENTRYPOINT. Needed when the image's own entrypoint "
        "ignores its arguments, so a command override alone would be discarded.",
        example="/opt/app/entrypoint_worker.sh",
    ),
    FieldEntry(
        "services[].secrets", _S.SERVICES, _P.COMMON, _C.REFERENCE_LIST,
        "Names of secrets entries to inject into this container.",
    ),
    FieldEntry(
        "services[].s3_access", _S.SERVICES, _P.COMMON, _C.REFERENCE_LIST,
        "Names of S3 bucket entries to grant read/write access.",
    ),
    FieldEntry(
        "services[].environment_variables.*", _S.SERVICES, _P.COMMON, _C.KEY_VALUE_MAP,
        "Static environment variables passed to the container.",
        example="LOG_LEVEL = info",
    ),
    FieldEntry(
        "services[].ulimits[].name", _S.SERVICES, _P.ADVANCED, _C.SELECT,
        "Linux ulimit name.",
        example="nofile",
    ),
    FieldEntry(
        "services[].ulimits[].soft_limit", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "Ulimit soft limit value.",
    ),
    FieldEntry(
        "services[].ulimits[].hard_limit", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "Ulimit hard limit value.",
    ),
    FieldEntry(
        "services[].enable_exec", _S.SERVICES, _P.ADVANCED, _C.BOOLEAN,
        "Enable ECS Exec for interactive shell access.",
    ),
    FieldEntry(
        "services[].enable_ses_send_email", _S.SERVICES, _P.ADVANCED, _C.BOOLEAN,
        "Grant this service SES send-email and quota-read permissions.",
    ),
    FieldEntry(
        "services[].launch_type", _S.SERVICES, _P.COMMON, _C.SELECT,
        "ECS launch type.",
        example="fargate",
    ),
    FieldEntry(
        "services[].ec2_instance_type", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "EC2 instance type; required when launch_type is ec2.",
        example="t3.medium",
    ),
    FieldEntry(
        "services[].architecture", _S.SERVICES, _P.ADVANCED, _C.SELECT,
        "CPU architecture; auto-detected from ec2_instance_type when empty.",
        example="arm64",
    ),
    FieldEntry(
        "services[].user_data_script", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Legacy path to an EC2 user-data shell script.",
    ),
    FieldEntry(
        "services[].user_data_script_content", _S.SERVICES, _P.ADVANCED, _C.TEXTAREA,
        "Inline EC2 user-data shell script content.",
    ),
    FieldEntry(
        "services[].enable_service_discovery", _S.SERVICES, _P.ADVANCED, _C.BOOLEAN,
        "Register this service with Cloud Map for inter-service DNS discovery.",
    ),
    FieldEntry(
        "services[].ebs_volumes[].name", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Logical EBS volume name for tagging and snapshot discovery.",
    ),
    FieldEntry(
        "services[].ebs_volumes[].size_gb", _S.SERVICES, _P.ADVANCED, _C.INTEGER,
        "EBS volume size in GiB.",
    ),
    FieldEntry(
        "services[].ebs_volumes[].mount_path", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Container filesystem mount path.",
        example="/data",
    ),
    FieldEntry(
        "services[].ebs_volumes[].device_name", _S.SERVICES, _P.ADVANCED, _C.TEXT,
        "Linux block device name.",
        example="/dev/xvdf",
    ),
    FieldEntry(
        "services[].ebs_volumes[].volume_type", _S.SERVICES, _P.ADVANCED, _C.SELECT,
        "EBS volume type.",
        example="gp3",
    ),
    FieldEntry(
        "services[].ebs_volumes[].filesystem_type", _S.SERVICES, _P.ADVANCED, _C.SELECT,
        "Filesystem to format the volume with.",
        example="ext4",
    ),
    # -- Routing (ALB + CloudFront) ---------------------------------------
    FieldEntry(
        "alb.mode", _S.ROUTING, _P.COMMON, _C.SELECT,
        "Shared looks up an existing ALB by name; dedicated provisions a new one.",
    ),
    FieldEntry(
        "alb.shared_alb_name", _S.ROUTING, _P.COMMON, _C.TEXT,
        "Name of the existing shared ALB to look up.",
    ),
    FieldEntry(
        "alb.shared_listener_arn", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "Explicit shared ALB listener ARN override; defaults to Automatic.",
    ),
    FieldEntry(
        "alb.shared_alb_security_group_id", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "Security group ID for the shared ALB listener; defaults to Automatic.",
    ),
    FieldEntry(
        "alb.certificate_arn", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "ACM certificate ARN; required when mode is dedicated.",
    ),
    FieldEntry(
        "alb.domain", _S.ROUTING, _P.COMMON, _C.TEXT,
        "Cluster hostname for ALB host-header routing.",
    ),
    FieldEntry(
        "alb.default_target_service", _S.ROUTING, _P.COMMON, _C.SERVICE_SELECT,
        "Service that receives the default host-header rule.",
    ),
    FieldEntry(
        "alb.default_listener_priority", _S.ROUTING, _P.ADVANCED, _C.INTEGER,
        "Preferred listener rule priority; deploy allocates one when empty.",
    ),
    FieldEntry(
        "alb.path_rules[].name", _S.ROUTING, _P.COMMON, _C.TEXT,
        "Path rule identifier.",
    ),
    FieldEntry(
        "alb.path_rules[].path_pattern", _S.ROUTING, _P.COMMON, _C.TEXT,
        "ALB path pattern for this rule.",
        example="/kibana/*",
    ),
    FieldEntry(
        "alb.path_rules[].target_service", _S.ROUTING, _P.COMMON, _C.SERVICE_SELECT,
        "Service that receives requests for this path.",
    ),
    FieldEntry(
        "alb.path_rules[].priority", _S.ROUTING, _P.ADVANCED, _C.INTEGER,
        "Preferred listener rule priority; deploy allocates one when empty.",
    ),
    FieldEntry(
        "cloudfront.enabled", _S.ROUTING, _P.COMMON, _C.BOOLEAN,
        "Create a CloudFront distribution in front of the ALB routing domain.",
    ),
    FieldEntry(
        "cloudfront.origin_https_only", _S.ROUTING, _P.ADVANCED, _C.BOOLEAN,
        "Connect to the ALB origin using HTTPS only.",
    ),
    FieldEntry(
        "cloudfront.custom_domain", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "Custom domain alias; must be paired with certificate_arn.",
    ),
    FieldEntry(
        "cloudfront.certificate_arn", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "ACM certificate ARN in us-east-1 for the custom domain.",
    ),
    FieldEntry(
        "cloudfront.price_class", _S.ROUTING, _P.ADVANCED, _C.SELECT,
        "CloudFront price class.",
    ),
    FieldEntry(
        "cloudfront.comment", _S.ROUTING, _P.ADVANCED, _C.TEXT,
        "Optional CloudFront distribution comment.",
    ),
    FieldEntry(
        "cloudfront.connections[].service", _S.ROUTING, _P.COMMON, _C.SERVICE_SELECT,
        "Service to receive a CloudFront URL env var.",
    ),
    FieldEntry(
        "cloudfront.connections[].env_key", _S.ROUTING, _P.COMMON, _C.TEXT,
        "Environment variable key for the CloudFront URL.",
        example="CDN_URL",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].name", _S.ROUTING, _P.COMMON, _C.TEXT,
        "Cached behavior identifier.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].path_pattern", _S.ROUTING, _P.COMMON, _C.TEXT,
        "CloudFront path pattern to cache.",
        example="/images/*",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].compress", _S.ROUTING, _P.ADVANCED, _C.BOOLEAN,
        "Enable compression for this behavior.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].cache_by_origin_headers", _S.ROUTING, _P.ADVANCED, _C.BOOLEAN,
        "Honor origin Cache-Control/Expires headers for this behavior.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].min_ttl_seconds", _S.ROUTING, _P.ADVANCED, _C.INTEGER,
        "Minimum TTL in seconds.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].default_ttl_seconds", _S.ROUTING, _P.ADVANCED, _C.INTEGER,
        "Default TTL in seconds when origin headers are absent.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].max_ttl_seconds", _S.ROUTING, _P.ADVANCED, _C.INTEGER,
        "Maximum TTL in seconds.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].query_strings", _S.ROUTING, _P.ADVANCED, _C.SELECT,
        "Query string forwarding mode.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].query_string_allowlist", _S.ROUTING, _P.ADVANCED, _C.STRING_LIST,
        "Allowed query keys when query_strings is allowlist.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].cookies", _S.ROUTING, _P.ADVANCED, _C.SELECT,
        "Cookie forwarding mode.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].cookie_allowlist", _S.ROUTING, _P.ADVANCED, _C.STRING_LIST,
        "Allowed cookie names when cookies is allowlist.",
    ),
    FieldEntry(
        "cloudfront.cached_behaviors[].forward_authorization_header", _S.ROUTING, _P.ADVANCED, _C.BOOLEAN,
        "Forward the Authorization header for this behavior.",
    ),
    # -- Database (RDS) ----------------------------------------------------
    FieldEntry(
        "rds.database_name", _S.DATABASE, _P.COMMON, _C.TEXT,
        "Name of the initial database.",
    ),
    FieldEntry(
        "rds.instance_type", _S.DATABASE, _P.COMMON, _C.TEXT,
        "RDS DB instance class.",
        example="db.t4g.micro",
    ),
    FieldEntry(
        "rds.allocated_storage_gb", _S.DATABASE, _P.COMMON, _C.INTEGER,
        "Disk size in GB.",
    ),
    FieldEntry(
        "rds.expose_to", _S.DATABASE, _P.COMMON, _C.REFERENCE_LIST,
        "Services that receive DB connection environment variables.",
    ),
    FieldEntry(
        "rds.engine_version", _S.DATABASE, _P.ADVANCED, _C.TEXT,
        "PostgreSQL major version.",
        example="15",
    ),
    FieldEntry(
        "rds.backup_retention_days", _S.DATABASE, _P.ADVANCED, _C.INTEGER,
        "Number of days to keep automated backups.",
    ),
    FieldEntry(
        "rds.initial_snapshot_identifier", _S.DATABASE, _P.ADVANCED, _C.TEXT,
        "Snapshot to restore prod from on its first deploy only.",
        example="legacy-prod-final-2026-08-14",
    ),
    FieldEntry(
        "rds.initial_snapshot_credentials_secret", _S.DATABASE, _P.ADVANCED, _C.TEXT,
        "Secrets Manager name/ARN with the snapshot source's username and password.",
    ),
    # -- Storage (S3) ------------------------------------------------------
    FieldEntry(
        "s3_buckets[].name", _S.STORAGE, _P.COMMON, _C.TEXT,
        "Logical bucket name; actual bucket is {project}-{env}-{name}.",
    ),
    FieldEntry(
        "s3_buckets[].mode", _S.STORAGE, _P.COMMON, _C.SELECT,
        "Bucket source mode.",
    ),
    FieldEntry(
        "s3_buckets[].existing_bucket_name", _S.STORAGE, _P.ADVANCED, _C.TEXT,
        "Existing bucket name to use when mode is existing.",
    ),
    FieldEntry(
        "s3_buckets[].seed_source_bucket_name", _S.STORAGE, _P.ADVANCED, _C.TEXT,
        "Source bucket for one-time seed copy when mode is seed-copy.",
    ),
    FieldEntry(
        "s3_buckets[].preview_fallback_bucket_name", _S.STORAGE, _P.ADVANCED, _C.TEXT,
        "Explicit fallback bucket active preview environments may read from.",
    ),
    FieldEntry(
        "s3_buckets[].preview_fallback_env_key", _S.STORAGE, _P.ADVANCED, _C.TEXT,
        "Env var name that receives the preview fallback bucket name.",
    ),
    FieldEntry(
        "s3_buckets[].seed_non_prod_only", _S.STORAGE, _P.ADVANCED, _C.BOOLEAN,
        "Run one-time seed copy only for non-prod environments.",
    ),
    FieldEntry(
        "s3_buckets[].public_read", _S.STORAGE, _P.COMMON, _C.BOOLEAN,
        "Grant public read access.",
    ),
    FieldEntry(
        "s3_buckets[].cloudfront", _S.STORAGE, _P.COMMON, _C.BOOLEAN,
        "Provision a CloudFront distribution in front of this bucket.",
    ),
    FieldEntry(
        "s3_buckets[].cors", _S.STORAGE, _P.ADVANCED, _C.BOOLEAN,
        "Enable permissive CORS headers.",
    ),
    FieldEntry(
        "s3_buckets[].connections[].service", _S.STORAGE, _P.COMMON, _C.SERVICE_SELECT,
        "Service to grant bucket access.",
    ),
    FieldEntry(
        "s3_buckets[].connections[].env_key", _S.STORAGE, _P.COMMON, _C.TEXT,
        "Env var name for the bucket name.",
        example="MEDIA_BUCKET",
    ),
    FieldEntry(
        "s3_buckets[].connections[].cloudfront_env_key", _S.STORAGE, _P.ADVANCED, _C.TEXT,
        "Env var name for the CloudFront URL (requires cloudfront=true).",
    ),
    FieldEntry(
        "s3_buckets[].connections[].read_only", _S.STORAGE, _P.ADVANCED, _C.BOOLEAN,
        "Grant read-only access instead of read/write.",
    ),
    # -- Secrets -----------------------------------------------------------
    FieldEntry(
        "secrets[].name", _S.SECRETS, _P.COMMON, _C.TEXT,
        "Environment variable name for the secret.",
        example="DJANGO_SECRET_KEY",
    ),
    FieldEntry(
        "secrets[].source", _S.SECRETS, _P.COMMON, _C.SELECT,
        "How the secret value is sourced.",
    ),
    FieldEntry(
        "secrets[].existing_secret_name", _S.SECRETS, _P.COMMON, _C.TEXT,
        "Existing Secrets Manager name/ARN, or RDS JSON key for source rds.",
    ),
    FieldEntry(
        "secrets[].length", _S.SECRETS, _P.ADVANCED, _C.INTEGER,
        "Character length for generated secrets.",
    ),
    FieldEntry(
        "secrets[].generate_once", _S.SECRETS, _P.ADVANCED, _C.BOOLEAN,
        "Generated values are created once per environment and reused.",
    ),
    # -- Environments (env list, per-env overrides, previews) --------------
    FieldEntry(
        "project.environments", _S.ENVIRONMENTS, _P.COMMON, _C.STRING_LIST,
        "Environment names; prod must be included and is placed first.",
        example="prod, staging",
    ),
    FieldEntry(
        "environments.*.instance_type_override", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Override the RDS instance type for this environment.",
    ),
    FieldEntry(
        "environments.*.tags.*", _S.ENVIRONMENTS, _P.ADVANCED, _C.KEY_VALUE_MAP,
        "Tags applied only when deploying this environment.",
    ),
    FieldEntry(
        "environments.*.alb.shared_alb_name", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Shared ALB to target in this environment instead of the project's.",
        example="global-dev",
    ),
    FieldEntry(
        "environments.*.alb.shared_listener_arn", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Shared ALB listener ARN for this environment. Set with the security "
        "group ID to skip name lookup.",
    ),
    FieldEntry(
        "environments.*.alb.shared_alb_security_group_id", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Security group on this environment's shared ALB listener.",
    ),
    FieldEntry(
        "environments.*.services.*.cpu", _S.ENVIRONMENTS, _P.ADVANCED, _C.INTEGER,
        "Task CPU units for one service in this environment.",
    ),
    FieldEntry(
        "environments.*.services.*.memory_mib", _S.ENVIRONMENTS, _P.ADVANCED, _C.INTEGER,
        "Task memory in MiB for one service in this environment.",
    ),
    FieldEntry(
        "environments.*.services.*.desired_count", _S.ENVIRONMENTS, _P.ADVANCED, _C.INTEGER,
        "Running task count for one service in this environment.",
    ),
    FieldEntry(
        "environments.*.services.*.environment_variables.*", _S.ENVIRONMENTS, _P.ADVANCED, _C.KEY_VALUE_MAP,
        "Environment variables merged over the service's own for this "
        "environment, key by key.",
    ),
    FieldEntry(
        "environments.*.ec2_instance_type_override.*", _S.ENVIRONMENTS, _P.ADVANCED, _C.KEY_VALUE_MAP,
        "Per-service EC2 instance type overrides for this environment.",
    ),
    FieldEntry(
        "preview_environments.enabled", _S.ENVIRONMENTS, _P.COMMON, _C.BOOLEAN,
        "Allow dynamic preview environments such as per-PR deployments.",
    ),
    FieldEntry(
        "preview_environments.base_environment", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Configured environment used as the preview source/template.",
    ),
    FieldEntry(
        "preview_environments.name_pattern", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Preview environment name pattern; must contain {number}.",
        example="pr-{number}",
    ),
    FieldEntry(
        "preview_environments.domain_template", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Preview hostname template; must contain {number} when set.",
    ),
    FieldEntry(
        "preview_environments.hosted_zone_name", _S.ENVIRONMENTS, _P.ADVANCED, _C.TEXT,
        "Route53 hosted zone name for preview DNS records.",
    ),
    FieldEntry(
        "preview_environments.listener_priority_start", _S.ENVIRONMENTS, _P.ADVANCED, _C.INTEGER,
        "Start of the shared ALB listener priority range reserved for previews.",
    ),
    FieldEntry(
        "preview_environments.listener_priority_end", _S.ENVIRONMENTS, _P.ADVANCED, _C.INTEGER,
        "End of the shared ALB listener priority range reserved for previews.",
    ),
    FieldEntry(
        "preview_environments.tags.*", _S.ENVIRONMENTS, _P.ADVANCED, _C.KEY_VALUE_MAP,
        "Tags applied only to dynamic preview environments.",
    ),
)


_REGISTRY_BY_PATH: dict[str, FieldEntry] = {}
for _entry in FIELD_REGISTRY:
    if _entry.path in _REGISTRY_BY_PATH:
        raise ValueError(f"Duplicate field registry entry for path {_entry.path!r}")
    _REGISTRY_BY_PATH[_entry.path] = _entry
