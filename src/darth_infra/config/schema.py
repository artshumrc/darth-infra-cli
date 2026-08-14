"""Schema-backed checking of the raw configuration document.

The packaged JSON Schema is the complete field surface. The dataclass parsers
read the keys they know and ignore everything else, so without this an
unrecognized key — a typo, or an option from a newer CLI — is discarded in
silence and the default is deployed in its place.

Only unknown keys are reported here. Types, ranges, and cross-field rules stay
with :class:`~darth_infra.config.models.ProjectConfig`, which produces better
messages than a generic validator could.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "darth-infra.schema.json"


class ConfigError(ValueError):
    """A problem with the config file itself, reportable as-is to the operator.

    Subclasses ValueError so existing handling of configuration failures is
    unaffected; the CLI catches this type specifically to print the message
    without a traceback.
    """


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load and parse the canonical packaged schema document."""
    return json.loads(Path(path).read_text())


@dataclass(frozen=True)
class UnknownKey:
    """A configuration key the schema does not define.

    Attributes:
        path: Dotted path to the key, with array indices, e.g.
            ``services[0].memory_mb``.
        suggestion: The closest defined key at that position, when one is close
            enough to be worth offering.
    """

    path: str
    suggestion: str | None


def unknown_keys(
    raw: dict[str, Any], schema: dict[str, Any] | None = None
) -> list[UnknownKey]:
    """Return every key in *raw* that the schema does not define."""
    found: list[UnknownKey] = []
    _walk(raw, schema if schema is not None else load_schema(), "", found)
    return found


def format_unknown_keys(keys: list[UnknownKey]) -> str:
    """Render unknown keys as a multi-line error message."""
    lines = []
    for key in keys:
        hint = f" (did you mean '{key.suggestion}'?)" if key.suggestion else ""
        lines.append(f"  {key.path}{hint}")
    return "Unrecognized configuration keys:\n" + "\n".join(lines)


def _walk(
    value: Any, node: dict[str, Any], path: str, found: list[UnknownKey]
) -> None:
    if isinstance(value, dict):
        _walk_object(value, node, path, found)
    elif isinstance(value, list):
        items = node.get("items")
        if isinstance(items, dict):
            for index, child in enumerate(value):
                _walk(child, items, f"{path}[{index}]", found)


def _walk_object(
    value: dict[str, Any], node: dict[str, Any], path: str, found: list[UnknownKey]
) -> None:
    properties = node.get("properties")
    # A dict here is the subschema for free-form keys (tags, env vars, the
    # per-environment table); False closes the object to its declared keys.
    additional = node.get("additionalProperties")

    if properties is None:
        if isinstance(additional, dict):
            for key, child in value.items():
                _walk(child, additional, _join(path, key), found)
        return

    for key, child in value.items():
        if key in properties:
            _walk(child, properties[key], _join(path, key), found)
        elif isinstance(additional, dict):
            _walk(child, additional, _join(path, key), found)
        elif additional is False:
            found.append(UnknownKey(_join(path, key), _suggest(key, properties)))


def _suggest(key: str, properties: dict[str, Any]) -> str | None:
    matches = get_close_matches(key, list(properties), n=1, cutoff=0.6)
    return matches[0] if matches else None


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key
