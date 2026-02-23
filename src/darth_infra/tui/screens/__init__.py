"""Compatibility re-exports for older imports.

TUI callers should use ``darth_infra.config.loader`` directly.
"""

from ...config.loader import dump_config, find_config, load_config

__all__ = ["dump_config", "find_config", "load_config"]
