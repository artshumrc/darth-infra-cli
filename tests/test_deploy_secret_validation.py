from __future__ import annotations

from darth_infra.cli.cfn import (
    _ecs_rollout_is_stable,
    _is_fatal_ecs_startup_message,
)


def test_rollout_stability_requires_active_single_deployment() -> None:
    assert _ecs_rollout_is_stable(
        {
            "rows": [
                {
                    "service": "web",
                    "status": "ACTIVE",
                    "running": "1",
                    "desired": "1",
                    "pending": "0",
                    "deployments": "1",
                }
            ]
        }
    )
    assert not _ecs_rollout_is_stable(
        {
            "rows": [
                {
                    "service": "web",
                    "status": "ACTIVE",
                    "running": "0",
                    "desired": "1",
                    "pending": "1",
                    "deployments": "2",
                }
            ]
        }
    )


def test_fatal_ecs_startup_message_detection_matches_secret_access_failures() -> None:
    assert _is_fatal_ecs_startup_message(
        "ResourceInitializationError: unable to pull secrets or registry auth"
    )
    assert _is_fatal_ecs_startup_message(
        "AccessDeniedException: no identity-based policy allows the secretsmanager:GetSecretValue action"
    )
    assert not _is_fatal_ecs_startup_message("service reached steady state")


if __name__ == "__main__":
    test_rollout_stability_requires_active_single_deployment()
    test_fatal_ecs_startup_message_detection_matches_secret_access_failures()
