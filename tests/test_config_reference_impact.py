"""Configuration reference impact and atomic service-deletion cleanup (ticket 07).

These tests exercise the widget-free reference-impact seam directly against a
:class:`ProjectDocument`: they inventory the references that involve a service,
cascade-delete a referenced service, prove no dangling reference survives, prove
the deletion is one reversible transaction, and prove referenced secret/bucket/
database resources are preserved.
"""

from __future__ import annotations

from pathlib import Path

from darth_infra.config.document import ProjectDocument
from darth_infra.config.loader import load_config
from darth_infra.config.reference_impact import (
    ReferenceKind,
    delete_service_with_references,
    external_service_references,
    rds_removal_references,
    remove_rds_with_references,
    service_references,
)

# A project where "web" is referenced by every reference category at once.
ALL_REFS = """\
[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000
launch_type = "ec2"
ec2_instance_type = "t3.medium"
secrets = ["DJANGO_SECRET_KEY"]
s3_access = ["media"]

[[services]]
name = "other"
port = 9000

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"

[rds]
database_name = "appdb"
expose_to = ["web", "other"]

[[s3_buckets]]
name = "media"
cloudfront = true

[[s3_buckets.connections]]
service = "web"
env_key = "MEDIA_BUCKET"

[alb]
domain = "demo.example.com"
default_target_service = "other"

[[alb.path_rules]]
name = "web-rule"
path_pattern = "/app/*"
target_service = "web"

[cloudfront]
enabled = true

[[cloudfront.connections]]
service = "web"
env_key = "CDN_URL"

[[cloudfront.cached_behaviors]]
name = "assets"
path_pattern = "/static/*"

[environments.prod.ec2_instance_type_override]
web = "t3.large"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "darth-infra.toml"
    path.write_text(text)
    return path


def test_service_references_lists_every_category(tmp_path: Path) -> None:
    doc = ProjectDocument.load(_write(tmp_path, ALL_REFS))
    refs = service_references(doc.config, "web")
    kinds = {ref.kind for ref in refs}
    assert ReferenceKind.ALB_PATH_RULE in kinds
    assert ReferenceKind.CLOUDFRONT_CONNECTION in kinds
    assert ReferenceKind.RDS_EXPOSE_TO in kinds
    assert ReferenceKind.S3_CONNECTION in kinds
    assert ReferenceKind.ENV_EC2_OVERRIDE in kinds
    # The service's own outgoing secret binding is reported too.
    assert ReferenceKind.SERVICE_SECRET in kinds
    assert ReferenceKind.SERVICE_S3_ACCESS in kinds


def test_alb_default_target_reported(tmp_path: Path) -> None:
    doc = ProjectDocument.load(_write(tmp_path, ALL_REFS))
    refs = service_references(doc.config, "other")
    kinds = {ref.kind for ref in refs}
    assert ReferenceKind.ALB_DEFAULT_TARGET in kinds


def test_external_references_exclude_owned_bindings(tmp_path: Path) -> None:
    doc = ProjectDocument.load(_write(tmp_path, ALL_REFS))
    external = external_service_references(doc.config, "web")
    assert all(not ref.owned_by_service for ref in external)
    kinds = {ref.kind for ref in external}
    assert ReferenceKind.SERVICE_SECRET not in kinds
    assert ReferenceKind.SERVICE_S3_ACCESS not in kinds


def test_delete_service_removes_all_references_atomically(tmp_path: Path) -> None:
    path = _write(tmp_path, ALL_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction():
        delete_service_with_references(doc, "web")

    config = doc.config  # must still parse: no dangling reference remains
    assert [s.name for s in config.services] == ["other"]
    assert all(rule.target_service != "web" for rule in config.alb.path_rules)
    assert all(conn.service != "web" for conn in config.cloudfront.connections)
    assert "web" not in config.rds.expose_to
    for bucket in config.s3_buckets:
        assert all(conn.service != "web" for conn in bucket.connections)
    assert "web" not in config.environment_overrides["prod"].ec2_instance_type_override
    # No external reference to "web" survives.
    assert external_service_references(config, "web") == []


def test_cleanup_preserves_referenced_resources(tmp_path: Path) -> None:
    path = _write(tmp_path, ALL_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction():
        delete_service_with_references(doc, "web")
    config = doc.config
    # The secret, bucket, and database themselves are not deleted.
    assert [s.name for s in config.secrets] == ["DJANGO_SECRET_KEY"]
    assert [b.name for b in config.s3_buckets] == ["media"]
    assert config.rds is not None and config.rds.database_name == "appdb"


def test_deletion_transaction_reverts(tmp_path: Path) -> None:
    path = _write(tmp_path, ALL_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction() as txn:
        delete_service_with_references(doc, "web")
        assert [s.name for s in doc.config.services] == ["other"]
    txn.revert()

    config = doc.config
    assert [s.name for s in config.services] == ["web", "other"]
    assert "web" in config.rds.expose_to
    assert any(rule.target_service == "web" for rule in config.alb.path_rules)
    assert any(conn.service == "web" for conn in config.cloudfront.connections)
    assert "web" in config.environment_overrides["prod"].ec2_instance_type_override


def test_deleted_service_document_still_saves(tmp_path: Path) -> None:
    path = _write(tmp_path, ALL_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction():
        delete_service_with_references(doc, "web")
    doc.save()
    reloaded = load_config(path)
    assert [s.name for s in reloaded.services] == ["other"]
    assert "web" not in reloaded.rds.expose_to


# A project whose RDS database is wired into every removal category at once:
# exposed services, a persisted RDS-backed secret with a service binding, and a
# per-environment RDS instance-type override.
RDS_REFS = """\
[project]
name = "demo"
environments = ["prod", "staging"]

[[services]]
name = "web"
port = 8000
secrets = ["DATABASE_HOST", "DJANGO_SECRET_KEY"]

[[secrets]]
name = "DATABASE_HOST"
source = "rds"
existing_secret_name = "host"

[[secrets]]
name = "DJANGO_SECRET_KEY"
source = "generate"

[rds]
database_name = "appdb"
expose_to = ["web"]
engine_version = "15"
backup_retention_days = 7

[environments.staging]
instance_type_override = "db.r6g.large"
"""


def test_rds_removal_references_lists_every_category(tmp_path: Path) -> None:
    doc = ProjectDocument.load(_write(tmp_path, RDS_REFS))
    kinds = {ref.kind for ref in rds_removal_references(doc.config)}
    assert ReferenceKind.RDS_EXPOSED_SERVICE in kinds
    assert ReferenceKind.RDS_SECRET_DECLARATION in kinds
    assert ReferenceKind.RDS_SECRET_BINDING in kinds
    assert ReferenceKind.RDS_ENV_INSTANCE_OVERRIDE in kinds


def test_rds_removal_references_empty_without_database(tmp_path: Path) -> None:
    doc = ProjectDocument.load(
        _write(
            tmp_path,
            "[project]\nname = \"demo\"\nenvironments = [\"prod\"]\n",
        )
    )
    assert rds_removal_references(doc.config) == []


def test_remove_rds_cleans_up_atomically(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction():
        remove_rds_with_references(doc)

    config = doc.config  # must still parse: nothing dangling remains
    assert config.rds is None
    # The RDS-backed secret declaration and its service binding are gone; the
    # unrelated generated secret survives.
    assert [s.name for s in config.secrets] == ["DJANGO_SECRET_KEY"]
    assert config.services[0].secrets == ["DJANGO_SECRET_KEY"]
    # The environment RDS instance-type override is cleared.
    assert config.environment_overrides["staging"].instance_type_override is None


def test_remove_rds_transaction_reverts(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction() as txn:
        remove_rds_with_references(doc)
        assert doc.config.rds is None
    txn.revert()

    config = doc.config
    assert config.rds is not None and config.rds.database_name == "appdb"
    assert "web" in config.rds.expose_to
    assert "DATABASE_HOST" in [s.name for s in config.secrets]
    assert "DATABASE_HOST" in config.services[0].secrets
    assert (
        config.environment_overrides["staging"].instance_type_override
        == "db.r6g.large"
    )


def test_removed_rds_document_still_saves(tmp_path: Path) -> None:
    path = _write(tmp_path, RDS_REFS)
    doc = ProjectDocument.load(path)
    with doc.transaction():
        remove_rds_with_references(doc)
    doc.save()
    reloaded = load_config(path)
    assert reloaded.rds is None
    assert [s.name for s in reloaded.secrets] == ["DJANGO_SECRET_KEY"]
