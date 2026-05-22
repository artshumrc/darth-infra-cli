from __future__ import annotations

from pathlib import Path

import pytest

from darth_infra.config.loader import dump_config, load_config
from darth_infra.config.models import (
    EnvironmentOverride,
    ProjectConfig,
    ServiceDiscoveryConfig,
    ServiceConfig,
)


def test_get_tags_for_environment_merges_with_environment_override() -> None:
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        tags={"owner": "platform", "cost-center": "shared"},
        environment_overrides={
            "dev": EnvironmentOverride(tags={"cost-center": "dev", "tier": "sandbox"})
        },
    )

    assert config.get_tags_for_environment("prod") == {
        "owner": "platform",
        "cost-center": "shared",
    }
    assert config.get_tags_for_environment("dev") == {
        "owner": "platform",
        "cost-center": "dev",
        "tier": "sandbox",
    }


def test_load_and_dump_environment_tags_roundtrip(tmp_path: Path) -> None:
    config_path = tmp_path / "darth-infra.toml"
    config_path.write_text(
        """#:schema ./darth-infra.schema.json

[project]
name = "demo"
environments = ["prod", "dev"]

[[services]]
name = "web"

[project.tags]
owner = "platform"

[environments.prod.tags]
compliance = "sox"

[environments.dev.tags]
cost-center = "dev"
owner = "developer-experience"
"""
    )

    loaded = load_config(config_path)

    assert loaded.environment_overrides["prod"].tags == {"compliance": "sox"}
    assert loaded.environment_overrides["dev"].tags == {
        "cost-center": "dev",
        "owner": "developer-experience",
    }
    assert loaded.get_tags_for_environment("dev") == {
        "owner": "developer-experience",
        "cost-center": "dev",
    }

    dumped = dump_config(loaded)

    assert "[environments.prod.tags]" in dumped
    assert '"compliance" = "sox"' in dumped
    assert "[environments.dev.tags]" in dumped
    assert '"cost-center" = "dev"' in dumped
    assert '"owner" = "developer-experience"' in dumped


def test_missing_service_discovery_config_keeps_legacy_local(tmp_path: Path) -> None:
    config_path = tmp_path / "darth-infra.toml"
    config_path.write_text(
        """[project]
name = "demo"

[[services]]
name = "web"
enable_service_discovery = true
"""
    )

    loaded = load_config(config_path)
    dumped = dump_config(loaded)

    assert loaded.service_discovery.namespace_template == "local"
    assert loaded.service_discovery_configured is False
    assert loaded.get_service_discovery_namespace("prod") == "local"
    assert "[service_discovery]" not in dumped


def test_service_discovery_config_roundtrip_and_render(tmp_path: Path) -> None:
    config_path = tmp_path / "darth-infra.toml"
    config_path.write_text(
        """[project]
name = "demo"

[service_discovery]
namespace_template = "{project}-{env}.local"

[[services]]
name = "web"
enable_service_discovery = true
"""
    )

    loaded = load_config(config_path)
    dumped = dump_config(loaded)

    assert loaded.service_discovery_configured is True
    assert loaded.get_service_discovery_namespace("prod") == "demo-prod.local"
    assert "[service_discovery]" in dumped
    assert 'namespace_template = "{project}-{env}.local"' in dumped


def test_service_discovery_rejects_invalid_namespace_template() -> None:
    with pytest.raises(ValueError, match="unsupported placeholder"):
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web")],
            service_discovery=ServiceDiscoveryConfig(
                namespace_template="{missing}.local"
            ),
            service_discovery_configured=True,
        )

    with pytest.raises(ValueError, match="labels must contain"):
        ProjectConfig(
            project_name="demo",
            services=[ServiceConfig(name="web")],
            service_discovery=ServiceDiscoveryConfig(
                namespace_template="{project}_prod.local"
            ),
            service_discovery_configured=True,
        )
