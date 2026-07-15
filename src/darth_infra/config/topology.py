"""Declared configuration topology for the Review screen.

Review shows a compact topology of the relationships an operator *declared* in
the configuration — CloudFront in front of ALB routing, ALB routes to services,
RDS exposure, S3 bucket connections, and secret bindings. It is explicitly a
view of the configuration draft, not of deployed AWS state and not a
CloudFormation plan.

The topology is derived from the *raw* document (presence-level reads) rather
than the validated :class:`~darth_infra.config.models.ProjectConfig`, so it still
renders when the draft is temporarily invalid — in particular when a reference
dangles (names a resource that does not exist). Such dangling relationships are
flagged and carry the owning editor location so Review can navigate to the
control responsible for fixing them.

This module knows nothing about Textual; it produces plain dataclasses the
Review widget renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "NODE_SERVICE",
    "NODE_RDS",
    "NODE_BUCKET",
    "NODE_SECRET",
    "NODE_CLOUDFRONT",
    "NODE_ALB",
    "TopologyNode",
    "TopologyEdge",
    "Topology",
    "derive_topology",
]

NODE_SERVICE = "service"
NODE_RDS = "rds"
NODE_BUCKET = "bucket"
NODE_SECRET = "secret"
NODE_CLOUDFRONT = "cloudfront"
NODE_ALB = "alb"


@dataclass(frozen=True)
class TopologyNode:
    """One declared resource in the configuration topology."""

    kind: str
    name: str


@dataclass(frozen=True)
class TopologyEdge:
    """One declared relationship between two resources.

    Attributes:
        source: Label of the originating resource.
        target: Label of the resource the relationship points at.
        label: Short description of the relationship (for example an env var key
            or a path pattern).
        dangling: True when ``target`` names a resource that is not declared, so
            the relationship cannot resolve. Dangling edges carry an owning
            editor location.
        owner_section: Value of the :class:`~darth_infra.tui.field_registry.Section`
            that owns the control responsible for a dangling edge, or ``None``.
        owner_path: Concrete document path of the offending reference, or
            ``None``.
    """

    source: str
    target: str
    label: str
    dangling: bool = False
    owner_section: str | None = None
    owner_path: str | None = None


@dataclass
class Topology:
    """The declared configuration topology: nodes and their relationships."""

    nodes: list[TopologyNode] = field(default_factory=list)
    edges: list[TopologyEdge] = field(default_factory=list)

    def nodes_of(self, kind: str) -> list[TopologyNode]:
        return [node for node in self.nodes if node.kind == kind]

    @property
    def dangling_edges(self) -> list[TopologyEdge]:
        return [edge for edge in self.edges if edge.dangling]

    @property
    def size(self) -> int:
        return len(self.nodes) + len(self.edges)


def _as_bool(value: Any) -> bool:
    return bool(value) and value not in ("false", "False", "0", 0)


def _record_names(document: Any, collection_path: str) -> list[str]:
    names: list[str] = []
    for index in range(document.record_count(collection_path)):
        record = document.raw_record(collection_path, index)
        name = record.get("name")
        if name:
            names.append(str(name))
    return names


def derive_topology(document: Any) -> Topology:
    """Derive the declared configuration topology from a project document.

    Reads only presence-level (raw) values, so it produces a topology even for a
    draft that fails model validation. Relationships whose target is not a
    declared resource are marked ``dangling`` and annotated with the owning
    editor so Review can navigate to the responsible control.
    """
    topology = Topology()

    service_names = _record_names(document, "services")
    bucket_names = _record_names(document, "s3_buckets")
    secret_names = _record_names(document, "secrets")

    for name in service_names:
        topology.nodes.append(TopologyNode(NODE_SERVICE, name))
    for name in bucket_names:
        topology.nodes.append(TopologyNode(NODE_BUCKET, name))
    for name in secret_names:
        topology.nodes.append(TopologyNode(NODE_SECRET, name))

    database_name = document.raw_value("rds.database_name")
    if database_name:
        topology.nodes.append(TopologyNode(NODE_RDS, str(database_name)))

    cloudfront_enabled = _as_bool(document.raw_value("cloudfront.enabled"))
    if cloudfront_enabled:
        topology.nodes.append(TopologyNode(NODE_CLOUDFRONT, "CloudFront"))

    alb_domain = document.raw_value("alb.domain")
    alb_default = document.raw_value("alb.default_target_service")
    alb_rule_count = document.record_count("alb.path_rules")
    has_alb = bool(alb_domain or alb_default or alb_rule_count)
    if has_alb:
        topology.nodes.append(TopologyNode(NODE_ALB, "ALB"))

    service_set = set(service_names)
    bucket_set = set(bucket_names)
    secret_set = set(secret_names)

    # CloudFront -> ALB (the distribution sits in front of ALB routing).
    if cloudfront_enabled and has_alb:
        topology.edges.append(
            TopologyEdge("CloudFront", "ALB", "distribution origin")
        )

    # CloudFront -> service connections (a CloudFront URL env var per service).
    for index in range(document.record_count("cloudfront.connections")):
        conn = document.raw_record("cloudfront.connections", index)
        service = str(conn.get("service", ""))
        env_key = str(conn.get("env_key", ""))
        if not service:
            continue
        topology.edges.append(
            TopologyEdge(
                "CloudFront",
                service,
                f"url as {env_key}" if env_key else "url",
                dangling=service not in service_set,
                owner_section="routing" if service not in service_set else None,
                owner_path=(
                    f"cloudfront.connections[{index}].service"
                    if service not in service_set
                    else None
                ),
            )
        )

    # ALB default target and path rules -> services.
    if alb_default:
        default = str(alb_default)
        topology.edges.append(
            TopologyEdge(
                "ALB",
                default,
                "default route",
                dangling=default not in service_set,
                owner_section="routing" if default not in service_set else None,
                owner_path=(
                    "alb.default_target_service"
                    if default not in service_set
                    else None
                ),
            )
        )
    for index in range(alb_rule_count):
        rule = document.raw_record("alb.path_rules", index)
        target = str(rule.get("target_service", ""))
        pattern = str(rule.get("path_pattern", ""))
        if not target:
            continue
        topology.edges.append(
            TopologyEdge(
                "ALB",
                target,
                f"route {pattern}" if pattern else "route",
                dangling=target not in service_set,
                owner_section="routing" if target not in service_set else None,
                owner_path=(
                    f"alb.path_rules[{index}].target_service"
                    if target not in service_set
                    else None
                ),
            )
        )

    # RDS -> exposed services.
    if database_name:
        expose_to = document.raw_value("rds.expose_to") or []
        for service in expose_to:
            service = str(service)
            topology.edges.append(
                TopologyEdge(
                    str(database_name),
                    service,
                    "exposed to",
                    dangling=service not in service_set,
                    owner_section=(
                        "database" if service not in service_set else None
                    ),
                    owner_path="rds.expose_to" if service not in service_set else None,
                )
            )

    # Buckets <-> services: bucket connections and service s3_access grants.
    for b_index in range(document.record_count("s3_buckets")):
        bucket = document.raw_record("s3_buckets", b_index)
        bucket_name = str(bucket.get("name", ""))
        if not bucket_name:
            continue
        for c_index, conn in enumerate(bucket.get("connections", []) or []):
            service = str(conn.get("service", ""))
            env_key = str(conn.get("env_key", ""))
            if not service:
                continue
            topology.edges.append(
                TopologyEdge(
                    bucket_name,
                    service,
                    f"as {env_key}" if env_key else "connection",
                    dangling=service not in service_set,
                    owner_section=(
                        "storage" if service not in service_set else None
                    ),
                    owner_path=(
                        f"s3_buckets[{b_index}].connections[{c_index}].service"
                        if service not in service_set
                        else None
                    ),
                )
            )

    # Services -> buckets (s3_access) and secrets (secret bindings).
    for s_index in range(document.record_count("services")):
        service = document.raw_record("services", s_index)
        service_name = str(service.get("name", ""))
        if not service_name:
            continue
        for bucket_name in service.get("s3_access", []) or []:
            bucket_name = str(bucket_name)
            topology.edges.append(
                TopologyEdge(
                    service_name,
                    bucket_name,
                    "access",
                    dangling=bucket_name not in bucket_set,
                    owner_section=(
                        "services" if bucket_name not in bucket_set else None
                    ),
                    owner_path=(
                        f"services[{s_index}].s3_access"
                        if bucket_name not in bucket_set
                        else None
                    ),
                )
            )
        for secret_name in service.get("secrets", []) or []:
            secret_name = str(secret_name)
            topology.edges.append(
                TopologyEdge(
                    service_name,
                    secret_name,
                    "secret",
                    dangling=secret_name not in secret_set,
                    owner_section=(
                        "services" if secret_name not in secret_set else None
                    ),
                    owner_path=(
                        f"services[{s_index}].secrets"
                        if secret_name not in secret_set
                        else None
                    ),
                )
            )

    return topology
