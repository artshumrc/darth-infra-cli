"""AWS discovery/verification adapter for the Guided editor.

Optional AWS lookups sit *behind an injected interface* rather than being called
directly from widgets. The editor never constructs boto clients or interprets
raw boto response dictionaries; it asks an :class:`AwsDiscovery` for domain
records (:class:`ResourceRecord`) and receives typed results
(:class:`DiscoveryResult`) and verification outcomes
(:class:`VerificationOutcome`). This keeps the editor testable with a
deterministic :class:`FakeAwsDiscovery` and keeps every AWS-shaped detail in one
place.

Three concerns are modelled:

* **Discovery** — list candidate resources so a reference can be *selected*
  rather than typed. :meth:`AwsDiscovery.discover` returns a
  :class:`DiscoveryResult` that distinguishes *loading* (the caller's own
  pre-call state), *success with results*, *empty*, and *failure*.
* **Verification** — user-triggered confirmation that a configured value exists
  in AWS. :meth:`AwsDiscovery.verify` returns ``Not checked`` / ``Verified`` /
  ``Check failed``. Verification is never a save prerequisite.
* **Parent filtering** — a :class:`DiscoveryRequest` carries the parent context
  (the VPC for subnet discovery, the load balancer for listener discovery) so
  dependent lookups stay relevant.

Local editing and saving never require this adapter to succeed: the default
:class:`OfflineAwsDiscovery` returns typed failures for every lookup, and manual
entry always remains available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

__all__ = [
    "DiscoveryKind",
    "DiscoveryRequest",
    "ResourceRecord",
    "DiscoveryFailure",
    "DiscoveryResult",
    "VerificationStatus",
    "VerificationOutcome",
    "AwsDiscovery",
    "OfflineAwsDiscovery",
    "FakeAwsDiscovery",
    "BotoAwsDiscovery",
]


class DiscoveryKind(str, Enum):
    """What an AWS-backed reference discovers/verifies.

    Each kind names the concrete resource a field selects, so the record's
    ``value`` is already the thing that field persists (a VPC *name* versus a VPC
    *id*, for example). Parent-scoped kinds read the parent identifiers from the
    :class:`DiscoveryRequest`.
    """

    VPC_NAME = "vpc_name"
    VPC_ID = "vpc_id"
    PRIVATE_SUBNETS = "private_subnets"
    PUBLIC_SUBNETS = "public_subnets"
    LOAD_BALANCER = "load_balancer"
    LISTENER = "listener"
    SECURITY_GROUP = "security_group"
    CERTIFICATE = "certificate"
    SECRET = "secret"


@dataclass(frozen=True)
class DiscoveryRequest:
    """A discovery/verification request with its parent context.

    ``vpc_id``/``vpc_name`` scope subnet discovery; ``load_balancer_arn``/
    ``load_balancer_name`` scope listener and security-group discovery. A field
    supplies whichever identifiers it currently has, and the adapter uses the
    most specific one available.
    """

    kind: DiscoveryKind
    vpc_id: str | None = None
    vpc_name: str | None = None
    load_balancer_arn: str | None = None
    load_balancer_name: str | None = None


@dataclass(frozen=True)
class ResourceRecord:
    """One discovered AWS resource as a domain record.

    Attributes:
        value: The value the owning field persists when this record is selected
            (e.g. a subnet id, a listener ARN, or an ALB name).
        label: Human-readable label for the picker.
        context: Extra identifiers a dependent lookup may need — e.g. a VPC
            record carries ``vpc_id`` so subnet discovery can be scoped, and an
            ALB record carries ``arn`` so listener discovery can be scoped.
    """

    value: str
    label: str
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryFailure:
    """A typed discovery/verification failure (never a raw boto exception)."""

    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    """The outcome of a discovery call.

    The four externally meaningful states are distinguished without overloading
    ``None``: *loading* is the caller's own pre-call state, while a returned
    result is *failure* (``failure`` set), *empty* (ok and no records), or
    *success with results*.
    """

    records: tuple[ResourceRecord, ...] = ()
    failure: DiscoveryFailure | None = None

    @property
    def ok(self) -> bool:
        """True when the lookup succeeded (whether or not it found anything)."""
        return self.failure is None

    @property
    def empty(self) -> bool:
        """True when the lookup succeeded but found no resources."""
        return self.ok and not self.records

    @classmethod
    def of(cls, records: list[ResourceRecord] | tuple[ResourceRecord, ...]) -> DiscoveryResult:
        return cls(records=tuple(records))

    @classmethod
    def failed(cls, message: str) -> DiscoveryResult:
        return cls(failure=DiscoveryFailure(message))


class VerificationStatus(str, Enum):
    """The three visible verification states."""

    NOT_CHECKED = "not_checked"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True)
class VerificationOutcome:
    """The result of a user-triggered verification."""

    status: VerificationStatus
    message: str = ""

    @classmethod
    def verified(cls, message: str = "") -> VerificationOutcome:
        return cls(VerificationStatus.VERIFIED, message)

    @classmethod
    def failed(cls, message: str) -> VerificationOutcome:
        return cls(VerificationStatus.FAILED, message)


@runtime_checkable
class AwsDiscovery(Protocol):
    """Injected AWS discovery/verification interface used by the editor.

    Implementations return domain records and typed failures; they never leak
    boto clients or raw response dictionaries to the editor. Later tickets
    (CloudFront, Secrets) may add methods, but this slice only needs discovery
    and verification of network/ALB resources.
    """

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        """List candidate resources for ``request`` as domain records."""
        ...

    def verify(self, request: DiscoveryRequest, target: str) -> VerificationOutcome:
        """Confirm that ``target`` exists in AWS for ``request``'s kind."""
        ...


class OfflineAwsDiscovery:
    """Default adapter for when no AWS access is configured.

    Every lookup returns a typed failure and every verification fails, so the
    editor is fully usable offline: discovery simply reports that manual entry is
    required, and saving never depends on it.
    """

    _MESSAGE = "AWS credentials are not configured; enter values manually."

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        return DiscoveryResult.failed(self._MESSAGE)

    def verify(self, request: DiscoveryRequest, target: str) -> VerificationOutcome:
        return VerificationOutcome.failed(self._MESSAGE)


class FakeAwsDiscovery:
    """Deterministic in-memory adapter for tests.

    Results are preconfigured per :class:`DiscoveryKind`; verification succeeds
    when a target is in the kind's known set. Every request is recorded on
    :attr:`requests` so tests can assert that parent choices scoped dependent
    lookups. An optional :attr:`gate` lets a test hold a call in its loading
    state before releasing it.
    """

    def __init__(
        self,
        *,
        results: dict[DiscoveryKind, DiscoveryResult] | None = None,
        known: dict[DiscoveryKind, set[str]] | None = None,
        gate: Callable[[], None] | None = None,
    ) -> None:
        self.results: dict[DiscoveryKind, DiscoveryResult] = dict(results or {})
        self.known: dict[DiscoveryKind, set[str]] = dict(known or {})
        self.gate = gate
        self.requests: list[DiscoveryRequest] = []
        self.verifications: list[tuple[DiscoveryRequest, str]] = []

    def set_result(self, kind: DiscoveryKind, result: DiscoveryResult) -> None:
        self.results[kind] = result

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        self.requests.append(request)
        if self.gate is not None:
            self.gate()
        return self.results.get(request.kind, DiscoveryResult())

    def verify(self, request: DiscoveryRequest, target: str) -> VerificationOutcome:
        self.verifications.append((request, target))
        if self.gate is not None:
            self.gate()
        if target and target in self.known.get(request.kind, set()):
            return VerificationOutcome.verified(f"{target} exists in AWS.")
        return VerificationOutcome.failed(
            f"{target or '(empty)'} was not found in AWS."
        )


class BotoAwsDiscovery:
    """Production adapter backed by boto3 clients.

    It maps raw boto responses to :class:`ResourceRecord`s and turns boto errors
    into :class:`DiscoveryFailure`/failed :class:`VerificationOutcome`s, so no
    boto detail reaches the editor. Clients are created lazily through an
    injectable ``client_factory`` (defaulting to ``boto3.client``) so the adapter
    can be exercised with fake clients without real AWS access.
    """

    def __init__(
        self,
        region_name: str,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._region = region_name
        self._client_factory = client_factory
        self._clients: dict[str, Any] = {}

    # -- client access -----------------------------------------------------

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            if self._client_factory is not None:
                self._clients[service] = self._client_factory(service)
            else:  # pragma: no cover - exercised only with real credentials
                import boto3

                self._clients[service] = boto3.client(
                    service, region_name=self._region
                )
        return self._clients[service]

    # -- discovery ---------------------------------------------------------

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        try:
            return self._discover(request)
        except Exception as exc:  # noqa: BLE001 - boto raises many error types
            return DiscoveryResult.failed(f"AWS lookup failed: {exc}")

    def _discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        kind = request.kind
        if kind in (DiscoveryKind.VPC_NAME, DiscoveryKind.VPC_ID):
            return self._discover_vpcs(kind)
        if kind in (DiscoveryKind.PRIVATE_SUBNETS, DiscoveryKind.PUBLIC_SUBNETS):
            return self._discover_subnets(request)
        if kind == DiscoveryKind.LOAD_BALANCER:
            return self._discover_load_balancers()
        if kind == DiscoveryKind.LISTENER:
            return self._discover_listeners(request)
        if kind == DiscoveryKind.SECURITY_GROUP:
            return self._discover_security_groups(request)
        if kind == DiscoveryKind.CERTIFICATE:
            return self._discover_certificates()
        if kind == DiscoveryKind.SECRET:
            return self._discover_secrets()
        return DiscoveryResult()  # pragma: no cover - defensive

    def _discover_vpcs(self, kind: DiscoveryKind) -> DiscoveryResult:
        ec2 = self._client("ec2")
        vpcs = ec2.describe_vpcs().get("Vpcs", [])
        records: list[ResourceRecord] = []
        for vpc in vpcs:
            vpc_id = str(vpc.get("VpcId", ""))
            name = _tag(vpc.get("Tags", []), "Name") or "(no Name tag)"
            cidr = vpc.get("CidrBlock", "?")
            value = name if kind == DiscoveryKind.VPC_NAME else vpc_id
            if not value or (kind == DiscoveryKind.VPC_NAME and name == "(no Name tag)"):
                # A field cannot select a value it cannot persist meaningfully.
                if kind == DiscoveryKind.VPC_NAME:
                    continue
            records.append(
                ResourceRecord(
                    value=value,
                    label=f"{name} ({vpc_id}, {cidr})",
                    context={"vpc_id": vpc_id, "vpc_name": name},
                )
            )
        return DiscoveryResult.of(records)

    def _resolve_vpc_id(self, request: DiscoveryRequest) -> str | None:
        if request.vpc_id:
            return request.vpc_id
        if not request.vpc_name:
            return None
        ec2 = self._client("ec2")
        vpcs = ec2.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [request.vpc_name]}]
        ).get("Vpcs", [])
        if not vpcs:
            return None
        return str(vpcs[0].get("VpcId", "")) or None

    def _discover_subnets(self, request: DiscoveryRequest) -> DiscoveryResult:
        vpc_id = self._resolve_vpc_id(request)
        if not vpc_id:
            return DiscoveryResult.failed(
                "Set a VPC (name or id) before discovering subnets."
            )
        ec2 = self._client("ec2")
        subnets = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("Subnets", [])
        want_public = request.kind == DiscoveryKind.PUBLIC_SUBNETS
        records: list[ResourceRecord] = []
        for subnet in subnets:
            is_public = bool(subnet.get("MapPublicIpOnLaunch", False))
            if is_public != want_public:
                continue
            subnet_id = str(subnet.get("SubnetId", ""))
            az = subnet.get("AvailabilityZone", "?")
            cidr = subnet.get("CidrBlock", "?")
            name = _tag(subnet.get("Tags", []), "Name") or "(no Name tag)"
            records.append(
                ResourceRecord(
                    value=subnet_id,
                    label=f"{name} ({subnet_id}, {az}, {cidr})",
                    context={"vpc_id": vpc_id},
                )
            )
        records.sort(key=lambda r: r.label)
        return DiscoveryResult.of(records)

    def _discover_load_balancers(self) -> DiscoveryResult:
        elbv2 = self._client("elbv2")
        records: list[ResourceRecord] = []
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for alb in page.get("LoadBalancers", []):
                if alb.get("Type") != "application":
                    continue
                name = str(alb.get("LoadBalancerName", ""))
                arn = str(alb.get("LoadBalancerArn", ""))
                scheme = alb.get("Scheme", "?")
                dns_name = alb.get("DNSName", "?")
                sgs = alb.get("SecurityGroups") or []
                records.append(
                    ResourceRecord(
                        value=name,
                        label=f"{name} ({scheme}, {dns_name})",
                        context={
                            "arn": arn,
                            "security_group_id": str(sgs[0]) if sgs else "",
                        },
                    )
                )
        return DiscoveryResult.of(records)

    def _resolve_load_balancer_arn(self, request: DiscoveryRequest) -> str | None:
        if request.load_balancer_arn:
            return request.load_balancer_arn
        if not request.load_balancer_name:
            return None
        elbv2 = self._client("elbv2")
        lbs = elbv2.describe_load_balancers(
            Names=[request.load_balancer_name]
        ).get("LoadBalancers", [])
        if not lbs:
            return None
        return str(lbs[0].get("LoadBalancerArn", "")) or None

    def _discover_listeners(self, request: DiscoveryRequest) -> DiscoveryResult:
        arn = self._resolve_load_balancer_arn(request)
        if not arn:
            return DiscoveryResult.failed(
                "Select a shared ALB before discovering listeners."
            )
        elbv2 = self._client("elbv2")
        listeners = elbv2.describe_listeners(LoadBalancerArn=arn).get("Listeners", [])
        records = [
            ResourceRecord(
                value=str(listener.get("ListenerArn", "")),
                label=(
                    f"{listener.get('Protocol', '?')}:{listener.get('Port', '?')} "
                    f"({listener.get('ListenerArn', '')})"
                ),
                context={"arn": arn},
            )
            for listener in listeners
        ]
        return DiscoveryResult.of(records)

    def _discover_security_groups(self, request: DiscoveryRequest) -> DiscoveryResult:
        arn = self._resolve_load_balancer_arn(request)
        if not arn:
            return DiscoveryResult.failed(
                "Select a shared ALB before discovering its security group."
            )
        elbv2 = self._client("elbv2")
        lbs = elbv2.describe_load_balancers(LoadBalancerArns=[arn]).get(
            "LoadBalancers", []
        )
        records: list[ResourceRecord] = []
        for lb in lbs:
            for sg in lb.get("SecurityGroups", []) or []:
                records.append(
                    ResourceRecord(
                        value=str(sg),
                        label=f"{sg} (from {lb.get('LoadBalancerName', '?')})",
                    )
                )
        return DiscoveryResult.of(records)

    def _discover_certificates(self) -> DiscoveryResult:
        # CloudFront certificates must live in us-east-1. Discovery is a
        # convenience only, so it lists issued ACM certificates and leaves the
        # region contract to deploy-time; manual ARN entry always remains.
        acm = self._client("acm")
        records: list[ResourceRecord] = []
        paginator = acm.get_paginator("list_certificates")
        for page in paginator.paginate(
            CertificateStatuses=["ISSUED"]
        ):
            for cert in page.get("CertificateSummaryList", []):
                arn = str(cert.get("CertificateArn", ""))
                if not arn:
                    continue
                domain = cert.get("DomainName", "?")
                records.append(
                    ResourceRecord(value=arn, label=f"{domain} ({arn})")
                )
        return DiscoveryResult.of(records)

    def _discover_secrets(self) -> DiscoveryResult:
        # Lists existing Secrets Manager secrets so an existing-secret reference
        # can be *selected* by name/ARN. Only identifiers and metadata are read:
        # ``list_secrets`` never returns and this never requests a secret value.
        sm = self._client("secretsmanager")
        records: list[ResourceRecord] = []
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate():
            for secret in page.get("SecretList", []):
                name = str(secret.get("Name", ""))
                if not name:
                    continue
                arn = str(secret.get("ARN", ""))
                description = secret.get("Description", "")
                detail = arn or "no ARN"
                if description:
                    detail = f"{detail}, {description}"
                records.append(
                    ResourceRecord(
                        value=name,
                        label=f"{name} ({detail})",
                        context={"arn": arn},
                    )
                )
        records.sort(key=lambda r: r.label)
        return DiscoveryResult.of(records)

    # -- verification ------------------------------------------------------

    def verify(self, request: DiscoveryRequest, target: str) -> VerificationOutcome:
        if not target:
            return VerificationOutcome.failed("No value to verify.")
        try:
            return self._verify(request, target)
        except Exception as exc:  # noqa: BLE001 - boto raises many error types
            return VerificationOutcome.failed(f"AWS verification failed: {exc}")

    def _verify(self, request: DiscoveryRequest, target: str) -> VerificationOutcome:
        kind = request.kind
        ec2 = None
        if kind == DiscoveryKind.VPC_NAME:
            ec2 = self._client("ec2")
            vpcs = ec2.describe_vpcs(
                Filters=[{"Name": "tag:Name", "Values": [target]}]
            ).get("Vpcs", [])
            if len(vpcs) == 1:
                return VerificationOutcome.verified(f"VPC '{target}' found.")
            return VerificationOutcome.failed(
                f"Expected exactly one VPC named '{target}', found {len(vpcs)}."
            )
        if kind == DiscoveryKind.VPC_ID:
            ec2 = self._client("ec2")
            vpcs = ec2.describe_vpcs(VpcIds=[target]).get("Vpcs", [])
            if len(vpcs) == 1:
                return VerificationOutcome.verified(f"VPC {target} found.")
            return VerificationOutcome.failed(f"VPC {target} was not found.")
        if kind == DiscoveryKind.LOAD_BALANCER:
            elbv2 = self._client("elbv2")
            lbs = elbv2.describe_load_balancers(Names=[target]).get(
                "LoadBalancers", []
            )
            if len(lbs) == 1:
                return VerificationOutcome.verified(f"ALB '{target}' found.")
            return VerificationOutcome.failed(f"ALB '{target}' was not found.")
        # Other kinds are selectable but not independently verifiable here.
        return VerificationOutcome(
            VerificationStatus.NOT_CHECKED,
            "Verification is not available for this field.",
        )


def _tag(tags: list[dict[str, str]], key: str) -> str | None:
    for tag in tags or []:
        if tag.get("Key") == key:
            return tag.get("Value")
    return None
