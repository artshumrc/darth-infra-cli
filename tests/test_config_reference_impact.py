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
