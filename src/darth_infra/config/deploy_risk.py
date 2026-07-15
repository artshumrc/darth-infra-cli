"""Deployment-sensitive change classification for the Review screen.

Review warns operators when the *unsaved diff* contains changes a future deploy
may act on destructively — replacing or removing managed infrastructure. This
module derives those warnings purely from the semantic diff
(:func:`~darth_infra.config.document.ProjectDocument.semantic_changes`); it does
not build an independent risk model or inspect AWS. Warnings are always phrased
as what a deploy *may* do, because only a real CloudFormation changeset can
assert an exact replacement or deletion.

The classification covers, at minimum, the identity change or removal of managed
RDS, managed buckets, the ALB mode, the environment set, service identity, and
network identity. Ordinary edits (an environment variable, a health-check path,
a tag) produce no warning.

Because the input is the semantic diff between the loaded/saved document and the
current draft, warnings appear only while that diff exists and disappear once it
is saved or reverted. Nothing here tracks a last-deployed configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .document import ChangeOperation, SemanticChange

__all__ = ["DeployRisk", "deployment_sensitive_changes"]


# Risk categories. Kept as short slugs so callers can group or test by category
# without matching on human-facing prose.
CATEGORY_SERVICE = "service_identity"
CATEGORY_RDS = "managed_rds"
CATEGORY_BUCKET = "managed_bucket"
CATEGORY_ALB_MODE = "alb_mode"
CATEGORY_ENVIRONMENT = "environment_identity"
CATEGORY_NETWORK = "network_identity"


@dataclass(frozen=True)
class DeployRisk:
    """One deployment-sensitive change derived from the semantic diff.

    Attributes:
        category: A stable slug identifying the kind of managed resource at
            risk (see the ``CATEGORY_*`` constants).
        summary: Human-readable, future-tense description of what a deploy may
            do. Never asserts an exact replacement or deletion.
        path: The semantic diff path that triggered the warning, retained so the
            Review screen can point at the originating change.
    """

    category: str
    summary: str
    path: str


# Network identity is any of these top-level project fields; a change to any one
# may force networked resources to be recreated at deploy time.
_NETWORK_PATHS = frozenset(
    {
        "project.aws_region",
        "project.vpc_name",
        "project.vpc_id",
        "project.private_subnet_ids",
        "project.public_subnet_ids",
    }
)

# A whole top-level record of a repeated collection, e.g. ``services[name=web]``.
_SERVICE_RECORD_RE = re.compile(r"^services\[[^\]]*\]$")
_SERVICE_NAME_RE = re.compile(r"^services\[[^\]]*\]\.name$")
_BUCKET_RECORD_RE = re.compile(r"^s3_buckets\[[^\]]*\]$")
_BUCKET_NAME_RE = re.compile(r"^s3_buckets\[[^\]]*\]\.name$")
_BUCKET_MODE_RE = re.compile(r"^s3_buckets\[[^\]]*\]\.mode$")


def _record_label(path: str) -> str:
    """Extract a readable resource label from an identity path.

    ``services[name=web]`` -> ``web``; ``s3_buckets[name=media].mode`` -> ``media``.
    Falls back to the raw path when no ``name=`` selector is present.
    """
    match = re.search(r"\[name=([^\],]*)", path)
    return match.group(1) if match else path


def deployment_sensitive_changes(
    changes: list[SemanticChange],
) -> list[DeployRisk]:
    """Return the deployment-sensitive warnings implied by ``changes``.

    Ordinary configuration edits yield an empty list. Singleton resources (RDS,
    ALB mode, the environment set, network identity) contribute at most one
    warning each even when several of their fields changed together; per-record
    resources (services, buckets) contribute one warning per affected record.
    Warnings are returned grouped by category in a stable order.
    """
    services: dict[str, DeployRisk] = {}
    buckets: dict[str, DeployRisk] = {}
    rds: DeployRisk | None = None
    alb_mode: DeployRisk | None = None
    environment: DeployRisk | None = None
    network: DeployRisk | None = None

    for change in changes:
        path = change.path
        op = change.operation

        # -- services (per-record identity) --------------------------------
        if _SERVICE_RECORD_RE.match(path):
            label = _record_label(path)
            if op is ChangeOperation.ADDED:
                summary = (
                    f"New service '{label}' will be created on the next deploy."
                )
            else:
                summary = (
                    f"Service '{label}' is no longer configured; a future deploy "
                    "may remove its ECS service and target group."
                )
            services[label] = DeployRisk(CATEGORY_SERVICE, summary, path)
            continue
        if _SERVICE_NAME_RE.match(path) and op is ChangeOperation.CHANGED:
            label = str(change.after)
            services[label] = DeployRisk(
                CATEGORY_SERVICE,
                f"Service renamed to '{label}'; a future deploy may replace the "
                "old ECS service and target group.",
                path,
            )
            continue

        # -- buckets (per-record identity / mode) --------------------------
        if _BUCKET_RECORD_RE.match(path):
            label = _record_label(path)
            if op is ChangeOperation.ADDED:
                summary = (
                    f"New bucket '{label}' will be created on the next deploy."
                )
            else:
                summary = (
                    f"Bucket '{label}' is no longer configured; a future deploy "
                    "may delete the managed S3 bucket and its contents."
                )
            buckets[label] = DeployRisk(CATEGORY_BUCKET, summary, path)
            continue
        if (_BUCKET_NAME_RE.match(path) or _BUCKET_MODE_RE.match(path)) and (
            op is ChangeOperation.CHANGED
        ):
            label = _record_label(path)
            buckets.setdefault(
                label,
                DeployRisk(
                    CATEGORY_BUCKET,
                    f"Bucket '{label}' identity or mode changed; a future deploy "
                    "may replace the managed S3 bucket.",
                    path,
                ),
            )
            continue

        # -- managed RDS (singleton) ---------------------------------------
        if path == "rds.database_name" or path.startswith("rds.") or path == "rds":
            if op is ChangeOperation.ADDED and path.startswith("rds."):
                rds = rds or DeployRisk(
                    CATEGORY_RDS,
                    "A managed database is now configured; the next deploy will "
                    "create the RDS instance.",
                    "rds",
                )
            else:
                rds = DeployRisk(
                    CATEGORY_RDS,
                    "Managed database identity changed or was removed; a future "
                    "deploy may replace or remove the RDS instance and its data.",
                    "rds",
                )
            continue

        # -- ALB mode (singleton) ------------------------------------------
        if path == "alb.mode":
            alb_mode = DeployRisk(
                CATEGORY_ALB_MODE,
                "ALB mode changed; a future deploy may move routing between a "
                "shared and a dedicated load balancer.",
                path,
            )
            continue

        # -- environment identity (singleton) ------------------------------
        if path == "project.environments":
            environment = DeployRisk(
                CATEGORY_ENVIRONMENT,
                "The environment list changed; a future deploy may create or "
                "tear down whole environment stacks.",
                path,
            )
            continue

        # -- network identity (singleton) ----------------------------------
        if path in _NETWORK_PATHS:
            network = DeployRisk(
                CATEGORY_NETWORK,
                "Network identity changed (region, VPC, or subnets); a future "
                "deploy may recreate networked resources.",
                path,
            )
            continue

    ordered: list[DeployRisk] = []
    ordered.extend(services[name] for name in sorted(services))
    if rds is not None:
        ordered.append(rds)
    ordered.extend(buckets[name] for name in sorted(buckets))
    if alb_mode is not None:
        ordered.append(alb_mode)
    if environment is not None:
        ordered.append(environment)
    if network is not None:
        ordered.append(network)
    return ordered
