"""darth-infra: Deploy websites to AWS ECS with multi-environment support."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("darth-infra")
except PackageNotFoundError:  # pragma: no cover - only for direct source-tree imports
    __version__ = "0.0.0"
