"""A configured tag key must not duplicate a built-in tag case-insensitively.

IAM compares tag keys case-insensitively and rejects a role carrying both
``Project`` and ``project`` with "Duplicate tag keys found", so the built-in has
to step aside for a configured key rather than sit beside it.
"""

from __future__ import annotations

from darth_infra.config.models import EnvironmentOverride, ProjectConfig, ServiceConfig
from darth_infra.scaffold.builders import build_project_templates

from builders_harness import template_to_dict

_NO_VALUE = {"Ref": "AWS::NoValue"}


def _rendered_keys(tags: list[dict[str, object]], *, conditions_true: bool) -> list[str]:
    """Tag keys CloudFormation actually emits, resolving every Fn::If one way.

    ``conditions_true`` stands in for "this environment sets its configured
    tags", which is the only axis these tags branch on.
    """
    keys: list[str] = []
    for tag in tags:
        if "Fn::If" in tag:
            _, when_true, when_false = tag["Fn::If"]
            resolved = when_true if conditions_true else when_false
            if resolved != _NO_VALUE:
                keys.append(resolved["Key"])
        else:
            keys.append(tag["Key"])
    return keys


def _tagged_resources(config: ProjectConfig) -> list[tuple[str, list[dict]]]:
    resources: list[tuple[str, list[dict]]] = []
    for path, template in build_project_templates(config).items():
        for logical_id, resource in template_to_dict(template)["Resources"].items():
            tags = resource.get("Properties", {}).get("Tags")
            if isinstance(tags, list):
                resources.append((f"{path}/{logical_id}", tags))
    return resources


def _assert_no_case_insensitive_duplicates(label: str, keys: list[str]) -> None:
    lowered = [key.lower() for key in keys]
    duplicates = {key for key in lowered if lowered.count(key) > 1}
    assert not duplicates, f"{label} emits {sorted(duplicates)} more than once: {keys}"


def _config(**tags: str) -> ProjectConfig:
    return ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        tags=tags,
    )


def test_no_resource_can_emit_a_duplicate_tag_key() -> None:
    resources = _tagged_resources(_config(project="demo", environment="prod"))

    assert resources, "expected at least one tagged resource"
    for label, tags in resources:
        for conditions_true in (True, False):
            _assert_no_case_insensitive_duplicates(
                f"{label} (conditions_true={conditions_true})",
                _rendered_keys(tags, conditions_true=conditions_true),
            )


def test_configured_key_wins_over_the_builtin_it_shadows() -> None:
    """The configured casing survives, because billing tag keys are case-sensitive."""
    for label, tags in _tagged_resources(_config(project="demo", environment="prod")):
        keys = _rendered_keys(tags, conditions_true=True)
        assert "project" in keys, f"{label} lost the configured key: {keys}"
        assert "environment" in keys, f"{label} lost the configured key: {keys}"
        assert "Project" not in keys, f"{label} kept the built-in: {keys}"
        assert "Environment" not in keys, f"{label} kept the built-in: {keys}"


def test_builtins_are_untouched_when_nothing_shadows_them() -> None:
    for label, tags in _tagged_resources(_config(owner="platform")):
        keys = _rendered_keys(tags, conditions_true=True)
        assert "Project" in keys, f"{label} lost the built-in Project tag: {keys}"
        assert "Environment" in keys, f"{label} lost Environment: {keys}"


def test_builtin_returns_for_an_environment_that_does_not_set_the_tag() -> None:
    """A tag configured only for dev must not strip prod's built-in.

    The configured tag is a stack parameter that is empty in prod, so suppressing
    the built-in unconditionally would leave prod resources untagged.
    """
    config = ProjectConfig(
        project_name="demo",
        services=[ServiceConfig(name="web")],
        environments=["prod", "dev"],
        environment_overrides={"dev": EnvironmentOverride(tags={"environment": "dev"})},
    )

    for label, tags in _tagged_resources(config):
        assert "Environment" in _rendered_keys(tags, conditions_true=False), (
            f"{label} has no Environment tag when the configured one is empty"
        )
        assert "environment" in _rendered_keys(tags, conditions_true=True), (
            f"{label} never emits the configured key"
        )
