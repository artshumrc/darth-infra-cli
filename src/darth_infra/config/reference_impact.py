"""Configuration reference impact: who points at a given resource.

Deleting a resource that other resources still reference must not leave the
configuration with dangling references. This module answers the question "what
references resource X?" over the *effective* configuration, and performs the
atomic cleanup a deletion requires. It is deliberately independent of the TUI:
it reasons over :class:`~darth_infra.config.models.ProjectConfig` and edits a
:class:`~darth_infra.config.document.ProjectDocument`, and knows nothing about
Textual widgets. Later Routing, Database, Storage, Secrets, and Environments
slices reuse this same seam.

Two halves live here:

* :func:`service_references` inventories every semantic reference that *involves*
  a named service — the external references that point *at* it (ALB default/path
  targets, CloudFront connections, RDS ``expose_to``, S3 connections, and
  per-environment EC2 instance overrides) as well as the service's own outgoing
  bindings to secrets and buckets (which are removed with the service record).
* :func:`delete_service_with_references` removes the service and every *external*
  reference to it in one batch of document edits. Callers wrap it in
  :meth:`ProjectDocument.transaction` so the whole cascade is atomic and
  reversible until it is saved.

Cleanup only removes references to the deleted service. It never deletes an
otherwise-valid secret, bucket, database, listener rule, or environment: the S3
bucket, secret, and RDS resources survive; only the connection/exposure that
named the deleted service is removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .models import ProjectConfig, SecretSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .document import ProjectDocument

__all__ = [
    "ReferenceKind",
    "ConfigReference",
    "service_references",
    "external_service_references",
    "delete_service_with_references",
    "rds_removal_references",
    "remove_rds_with_references",
]


class ReferenceKind(str, Enum):
    """The kind of a single reference that involves a service."""

    ALB_DEFAULT_TARGET = "alb_default_target"
    ALB_PATH_RULE = "alb_path_rule"
    CLOUDFRONT_CONNECTION = "cloudfront_connection"
    RDS_EXPOSE_TO = "rds_expose_to"
    S3_CONNECTION = "s3_connection"
    ENV_EC2_OVERRIDE = "env_ec2_override"
    SERVICE_SECRET = "service_secret"
    SERVICE_S3_ACCESS = "service_s3_access"
    # RDS-removal categories: what removing the singleton database affects.
    RDS_EXPOSED_SERVICE = "rds_exposed_service"
    RDS_SECRET_DECLARATION = "rds_secret_declaration"
    RDS_SECRET_BINDING = "rds_secret_binding"
    RDS_ENV_INSTANCE_OVERRIDE = "rds_env_instance_override"


@dataclass(frozen=True)
class ConfigReference:
    """One semantic reference that involves a service.

    Attributes:
        kind: Which category of reference this is.
        description: Human-readable summary suitable for a confirmation dialog.
        document_path: Concrete document path of the referencing element (a
            scalar to reset, or a collection element / map key to remove).
        owned_by_service: True when the reference lives inside the service's own
            record (its secret or bucket bindings). Such references vanish when
            the service record is removed and need no separate cleanup; external
            references (``owned_by_service`` is False) must be cleaned up
            explicitly to avoid dangling references.
    """

    kind: ReferenceKind
    description: str
    document_path: str
    owned_by_service: bool


def _service_index(config: ProjectConfig, name: str) -> int | None:
    for index, service in enumerate(config.services):
        if service.name == name:
            return index
    return None


def service_references(config: ProjectConfig, name: str) -> list[ConfigReference]:
    """Return every semantic reference that involves the service ``name``.

    Includes external references that point at the service and the service's own
    outgoing secret and bucket bindings. Order is stable and grouped by kind.
    """
    refs: list[ConfigReference] = []

    alb = config.alb
    if getattr(alb, "default_target_service", None) == name:
        refs.append(
            ConfigReference(
                ReferenceKind.ALB_DEFAULT_TARGET,
                "ALB default target service",
                "alb.default_target_service",
                owned_by_service=False,
            )
        )
    for index, rule in enumerate(alb.path_rules or []):
        if rule.target_service == name:
            refs.append(
                ConfigReference(
                    ReferenceKind.ALB_PATH_RULE,
                    f"ALB path rule '{rule.name}'",
                    f"alb.path_rules[{index}]",
                    owned_by_service=False,
                )
            )

    for index, conn in enumerate(config.cloudfront.connections or []):
        if conn.service == name:
            refs.append(
                ConfigReference(
                    ReferenceKind.CLOUDFRONT_CONNECTION,
                    f"CloudFront connection '{conn.env_key}'",
                    f"cloudfront.connections[{index}]",
                    owned_by_service=False,
                )
            )

    rds = getattr(config, "rds", None)
    if rds and name in (rds.expose_to or []):
        index = list(rds.expose_to).index(name)
        refs.append(
            ConfigReference(
                ReferenceKind.RDS_EXPOSE_TO,
                "database expose_to list",
                f"rds.expose_to[{index}]",
                owned_by_service=False,
            )
        )

    for b_index, bucket in enumerate(config.s3_buckets or []):
        for c_index, conn in enumerate(bucket.connections or []):
            if conn.service == name:
                refs.append(
                    ConfigReference(
                        ReferenceKind.S3_CONNECTION,
                        f"S3 bucket '{bucket.name}' connection ({conn.env_key})",
                        f"s3_buckets[{b_index}].connections[{c_index}]",
                        owned_by_service=False,
                    )
                )

    for env, override in config.environment_overrides.items():
        if name in (override.ec2_instance_type_override or {}):
            refs.append(
                ConfigReference(
                    ReferenceKind.ENV_EC2_OVERRIDE,
                    f"environment '{env}' EC2 instance type override",
                    f"environments.{env}.ec2_instance_type_override.{name}",
                    owned_by_service=False,
                )
            )

    svc_index = _service_index(config, name)
    if svc_index is not None:
        service = config.services[svc_index]
        for index, secret_name in enumerate(service.secrets or []):
            refs.append(
                ConfigReference(
                    ReferenceKind.SERVICE_SECRET,
                    f"secret binding '{secret_name}'",
                    f"services[{svc_index}].secrets[{index}]",
                    owned_by_service=True,
                )
            )
        for index, bucket_name in enumerate(service.s3_access or []):
            refs.append(
                ConfigReference(
                    ReferenceKind.SERVICE_S3_ACCESS,
                    f"S3 access grant '{bucket_name}'",
                    f"services[{svc_index}].s3_access[{index}]",
                    owned_by_service=True,
                )
            )

    return refs


def external_service_references(
    config: ProjectConfig, name: str
) -> list[ConfigReference]:
    """Return only the external references that point at the service ``name``.

    These are the references that would dangle if the service were removed
    without cleanup; the service's own owned bindings are excluded.
    """
    return [r for r in service_references(config, name) if not r.owned_by_service]


def delete_service_with_references(document: "ProjectDocument", name: str) -> None:
    """Remove the service ``name`` and every external reference to it.

    Performs one batch of document edits: scalars are reset, referencing
    collection elements are removed, per-environment overrides keyed by the
    service are removed, and finally the service record itself is removed. The
    referenced secret, bucket, and database resources are left intact. Callers
    should wrap this in :meth:`ProjectDocument.transaction` so the cascade is
    atomic and reversible.
    """
    config = document.config

    # Scalar reference: clear the ALB default target.
    if getattr(config.alb, "default_target_service", None) == name:
        document.reset("alb.default_target_service")

    # RDS exposure: drop the service from the list (removing the key if empty).
    rds = getattr(config, "rds", None)
    if rds and name in (rds.expose_to or []):
        remaining = [svc for svc in rds.expose_to if svc != name]
        if remaining:
            document.set("rds.expose_to", remaining)
        else:
            document.reset("rds.expose_to")

    # Collection references: remove by descending index so earlier removals do
    # not shift the indices of not-yet-removed elements.
    config = document.config
    for index in reversed(range(len(config.alb.path_rules))):
        if config.alb.path_rules[index].target_service == name:
            document.remove_record("alb.path_rules", index)

    config = document.config
    for index in reversed(range(len(config.cloudfront.connections))):
        if config.cloudfront.connections[index].service == name:
            document.remove_record("cloudfront.connections", index)

    config = document.config
    for b_index, bucket in enumerate(config.s3_buckets):
        for c_index in reversed(range(len(bucket.connections))):
            if bucket.connections[c_index].service == name:
                document.remove_record(f"s3_buckets[{b_index}].connections", c_index)

    # Per-environment EC2 instance overrides keyed by the service name.
    config = document.config
    for env, override in config.environment_overrides.items():
        if name in (override.ec2_instance_type_override or {}):
            document.reset(
                f"environments.{env}.ec2_instance_type_override.{name}"
            )

    # Finally the service record itself (its owned secret/bucket bindings go
    # with it; the secret and bucket resources themselves are untouched).
    config = document.config
    svc_index = _service_index(config, name)
    if svc_index is not None:
        document.remove_record("services", svc_index)


def _rds_secret_names(config: ProjectConfig) -> set[str]:
    """Names of persisted secrets whose source is the RDS database."""
    return {
        secret.name
        for secret in config.secrets
        if secret.source == SecretSource.RDS
    }


def rds_removal_references(config: ProjectConfig) -> list[ConfigReference]:
    """Return every configuration item removing the RDS database would affect.

    Removing the singleton database drops the ``[rds]`` table and everything that
    only made sense while it existed: the derived connection environment
    variables each exposed service received, any persisted RDS-backed secret
    declarations and the service bindings to them (managed by existing RDS secret
    behavior), and per-environment RDS instance-type overrides. Order is stable
    and grouped by kind. Returns an empty list when no database is configured.
    """
    refs: list[ConfigReference] = []
    rds = getattr(config, "rds", None)
    if rds is None:
        return refs

    for index, svc_name in enumerate(rds.expose_to or []):
        refs.append(
            ConfigReference(
                ReferenceKind.RDS_EXPOSED_SERVICE,
                f"database connection env vars for service '{svc_name}'",
                f"rds.expose_to[{index}]",
                owned_by_service=False,
            )
        )

    rds_secret_names = _rds_secret_names(config)
    for index, secret in enumerate(config.secrets):
        if secret.name in rds_secret_names:
            refs.append(
                ConfigReference(
                    ReferenceKind.RDS_SECRET_DECLARATION,
                    f"RDS-backed secret declaration '{secret.name}'",
                    f"secrets[{index}]",
                    owned_by_service=False,
                )
            )

    for svc_index, service in enumerate(config.services):
        for index, secret_name in enumerate(service.secrets or []):
            if secret_name in rds_secret_names:
                refs.append(
                    ConfigReference(
                        ReferenceKind.RDS_SECRET_BINDING,
                        f"secret binding '{secret_name}' on service '{service.name}'",
                        f"services[{svc_index}].secrets[{index}]",
                        owned_by_service=False,
                    )
                )

    for env, override in config.environment_overrides.items():
        if override.instance_type_override is not None:
            refs.append(
                ConfigReference(
                    ReferenceKind.RDS_ENV_INSTANCE_OVERRIDE,
                    f"environment '{env}' RDS instance-type override",
                    f"environments.{env}.instance_type_override",
                    owned_by_service=False,
                )
            )

    return refs


def remove_rds_with_references(document: "ProjectDocument") -> None:
    """Remove the RDS database and every reference that depended on it.

    Performs one batch of document edits: service bindings to RDS-backed secrets
    are dropped, per-environment RDS instance-type overrides are removed, the
    RDS-backed secret declarations are removed, and finally the ``[rds]`` table
    itself is removed. Non-RDS secrets, services, and environment settings are
    left intact. Callers should wrap this in :meth:`ProjectDocument.transaction`
    so the whole removal is atomic and reversible until it is saved.
    """
    config = document.config
    rds_secret_names = _rds_secret_names(config)

    # Service bindings to RDS-backed secrets (arrays of scalar names).
    if rds_secret_names:
        for svc_index, service in enumerate(config.services):
            remaining = [
                name for name in service.secrets if name not in rds_secret_names
            ]
            if len(remaining) != len(service.secrets):
                if remaining:
                    document.set(f"services[{svc_index}].secrets", remaining)
                else:
                    document.reset(f"services[{svc_index}].secrets")

    # Per-environment RDS instance-type overrides.
    config = document.config
    for env, override in config.environment_overrides.items():
        if override.instance_type_override is not None:
            document.reset(f"environments.{env}.instance_type_override")

    # RDS-backed secret declarations, removed by descending index so earlier
    # removals do not shift the indices of not-yet-removed records.
    config = document.config
    for index in reversed(range(len(config.secrets))):
        if config.secrets[index].name in rds_secret_names:
            document.remove_record("secrets", index)

    # Finally the [rds] table itself.
    document.reset("rds")
