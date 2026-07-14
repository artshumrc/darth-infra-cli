"""Document-preserving editing for an existing ``darth-infra.toml``.

This module is the deep, self-contained seam the Guided editor uses to edit an
existing project configuration *without* rewriting unrelated document content.
The canonical :func:`~darth_infra.config.loader.load_config` /
:func:`~darth_infra.config.loader.dump_config` pair are semantic interfaces:
they parse into (and serialize from) a validated :class:`ProjectConfig` and
therefore cannot preserve comments, ordering, quoting, or the distinction
between an omitted default and an explicit value that happens to equal that
default. New-project output continues to use ``dump_config``; this module is for
editing documents that already exist.

The interface is deliberately small. Callers never touch the underlying TOML
AST or maintain a parallel state dictionary; they address fields with the same
path notation established by the field registry (ticket 01), concretized with
real array indices and map keys:

    document = ProjectDocument.load(path)
    document.config                    # effective, validated ProjectConfig
    document.value("services[0].cpu")  # effective value (default-aware)
    document.is_explicit("services[0].cpu")
    document.set("services[0].cpu", 512)
    document.reset("services[0].cpu")  # remove the key, restore omission
    document.validate()                # inspect without raising
    document.toml_patch()              # exact textual diff that save would write
    document.save(expected_revision=document.revision)

Two orthogonal facts are exposed per field:

* :meth:`ProjectDocument.value` returns the *effective* value, exactly as the
  loader/model would compute it (defaults applied, normalization included).
* :meth:`ProjectDocument.is_explicit` reports raw document *presence*, which is
  independent of model normalization. An omitted default and an explicit value
  equal to that default therefore share a value but differ in presence.

Saving compares the on-disk content revision captured at load time with the
current file. A concurrent external change raises :class:`DocumentConflictError`
and never overwrites the newer file (three-way merge is ticket 03). A save is
atomic: the new text is written to a temporary sibling and then atomically
renamed over the target.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import tomlkit
from tomlkit import TOMLDocument

from .loader import _parse_project
from .models import ProjectConfig

__all__ = [
    "ProjectDocument",
    "ValidationResult",
    "DocumentConflictError",
    "DocumentValidationError",
]

# Path segments: a bare key (``name``) or an array index (``[0]``). Map keys are
# ordinary key segments. This mirrors the registry's ``[]`` / ``.*`` notation
# with the wildcards concretized to real indices and keys.
_SEGMENT_RE = re.compile(r"[^.\[\]]+|\[\d+\]")

# Loader table name -> ProjectConfig attribute, for the flattened ``[project]``
# table and the renamed ``[environments]`` table. Everything else maps by an
# identical name.
_PROJECT_FIELD_ALIASES = {"name": "project_name"}

_MISSING = object()


class DocumentConflictError(Exception):
    """Raised when the on-disk file changed since the document was loaded.

    The save is refused; the newer file is left untouched. Attributes carry the
    revision the caller expected and the revision actually found on disk.
    """

    def __init__(self, expected_revision: str, actual_revision: str) -> None:
        super().__init__(
            "darth-infra.toml changed on disk since it was loaded; refusing to "
            "overwrite it (expected revision "
            f"{expected_revision[:12]}, found {actual_revision[:12]})"
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class DocumentValidationError(Exception):
    """Raised when a save is attempted on a draft that fails model validation."""

    def __init__(self, error: str) -> None:
        super().__init__(f"cannot save an invalid configuration: {error}")
        self.error = error


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of validating the current draft against model semantics."""

    ok: bool
    error: str | None = None


def _parse_path(field_path: str) -> list[str | int]:
    """Split a concrete field path into key and index segments."""
    segments: list[str | int] = []
    for token in _SEGMENT_RE.findall(field_path):
        if token.startswith("["):
            segments.append(int(token[1:-1]))
        else:
            segments.append(token)
    if not segments:
        raise ValueError(f"empty field path: {field_path!r}")
    return segments


def _unwrap_enum(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


class ProjectDocument:
    """An editable, comment-preserving view of an existing project document."""

    def __init__(self, path: Path, text: str) -> None:
        self._path = Path(path)
        self._baseline_text = text
        self._revision = _hash(text)
        self._doc: TOMLDocument = tomlkit.parse(text)
        # Lazily built effective config; ``_MISSING`` means "not yet computed".
        self._config_cache: Any = _MISSING

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> ProjectDocument:
        """Load ``path`` into an editable document, preserving its exact text."""
        path = Path(path)
        return cls(path, path.read_text())

    # -- identity ----------------------------------------------------------

    @property
    def path(self) -> Path:
        """The file this document was loaded from and will be saved to."""
        return self._path

    @property
    def revision(self) -> str:
        """Content-based revision of the last loaded or saved document text."""
        return self._revision

    # -- effective model ---------------------------------------------------

    @property
    def config(self) -> ProjectConfig:
        """The effective, validated :class:`ProjectConfig` for the current draft.

        Raises the underlying loader/model error if the draft is invalid. Use
        :meth:`validate` to inspect validity without raising.
        """
        if self._config_cache is _MISSING:
            self._config_cache = _parse_project(self._doc.unwrap())
        return self._config_cache

    def validate(self) -> ValidationResult:
        """Validate the current draft through the loader/model without raising."""
        try:
            self.config
        except (ValueError, KeyError, TypeError) as exc:
            return ValidationResult(ok=False, error=str(exc))
        return ValidationResult(ok=True)

    # -- field inspection --------------------------------------------------

    def value(self, field_path: str) -> Any:
        """Return the effective value at ``field_path``.

        The value is what the loader/model would compute: explicit values when
        present, otherwise the effective default, with enums unwrapped to their
        string value. Optional blocks that are absent resolve to ``None``.
        """
        segments = _remap_to_config(_parse_path(field_path))
        obj: Any = self.config
        for segment in segments:
            if obj is None:
                return None
            obj = _descend_model(obj, segment)
            if obj is _MISSING:
                return None
        return _unwrap_enum(obj)

    def is_explicit(self, field_path: str) -> bool:
        """Report whether ``field_path`` is explicitly present in the document.

        Presence is a raw-document fact independent of model normalization: an
        omitted default and an explicit value equal to that default both report
        the same effective :meth:`value` but different ``is_explicit`` results.
        """
        obj: Any = self._doc
        for segment in _parse_path(field_path):
            child = _descend_raw(obj, segment)
            if child is _MISSING:
                return False
            obj = child
        return True

    # -- editing -----------------------------------------------------------

    def set(self, field_path: str, value: Any) -> None:
        """Persist ``value`` at ``field_path`` explicitly, editing in place."""
        segments = _parse_path(field_path)
        container = self._resolve_container(segments[:-1], create=True)
        container[segments[-1]] = value
        self._invalidate()

    def reset(self, field_path: str) -> None:
        """Remove the persisted key at ``field_path``, restoring omission.

        This deletes the key rather than writing its current default value. If
        the key is already absent this is a no-op.
        """
        segments = _parse_path(field_path)
        container = self._resolve_container(segments[:-1], create=False)
        if container is _MISSING:
            return
        last = segments[-1]
        try:
            present = last in container if isinstance(last, str) else (
                isinstance(last, int) and 0 <= last < len(container)
            )
        except TypeError:
            present = False
        if present:
            del container[last]
            self._invalidate()

    # -- output ------------------------------------------------------------

    def to_toml(self) -> str:
        """Return the current draft serialized to TOML text (without saving)."""
        return tomlkit.dumps(self._doc)

    def toml_patch(self) -> str:
        """Return the exact unified textual diff a save would write.

        Empty string when the draft matches the loaded document.
        """
        current = self.to_toml()
        if current == self._baseline_text:
            return ""
        diff = difflib.unified_diff(
            self._baseline_text.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"{self._path.name} (loaded)",
            tofile=f"{self._path.name} (draft)",
        )
        return "".join(diff)

    def save(self, expected_revision: str | None = None) -> str:
        """Atomically write the draft, returning the new content revision.

        Args:
            expected_revision: The revision the caller expects the on-disk file
                to still be at. Defaults to this document's current revision.

        Raises:
            DocumentValidationError: The draft fails model validation; nothing
                is written.
            DocumentConflictError: The on-disk file changed since the expected
                revision; the newer file is left intact (three-way merge is
                ticket 03).
        """
        expected = self._revision if expected_revision is None else expected_revision

        result = self.validate()
        if not result.ok:
            raise DocumentValidationError(result.error or "invalid configuration")

        if self._path.exists():
            actual = _hash(self._path.read_text())
            if actual != expected:
                raise DocumentConflictError(expected, actual)

        text = self.to_toml()
        _atomic_write(self._path, text)
        self._baseline_text = text
        self._revision = _hash(text)
        return self._revision

    # -- internals ---------------------------------------------------------

    def _invalidate(self) -> None:
        self._config_cache = _MISSING

    def _resolve_container(
        self, segments: list[str | int], *, create: bool
    ) -> Any:
        """Return the container holding the final path segment.

        With ``create=True``, missing intermediate tables are created. Array
        elements are never fabricated: an index into a missing or too-short
        array raises. With ``create=False``, a missing container returns
        :data:`_MISSING`.
        """
        obj: Any = self._doc
        for index, segment in enumerate(segments):
            if isinstance(segment, int):
                if not _has_index(obj, segment):
                    if create:
                        raise KeyError(
                            f"cannot address array element [{segment}] in a path "
                            "whose array does not have that element"
                        )
                    return _MISSING
                obj = obj[segment]
                continue

            if segment in obj:
                obj = obj[segment]
                continue

            if not create:
                return _MISSING

            next_is_index = index + 1 < len(segments) and isinstance(
                segments[index + 1], int
            )
            if next_is_index:
                raise KeyError(
                    f"cannot create array container for missing key {segment!r}"
                )
            obj[segment] = tomlkit.table()
            obj = obj[segment]
        return obj


def _descend_model(obj: Any, segment: str | int) -> Any:
    """Descend one segment into a parsed model object; ``_MISSING`` if absent."""
    if isinstance(segment, int):
        if isinstance(obj, (list, tuple)) and 0 <= segment < len(obj):
            return obj[segment]
        return _MISSING
    if isinstance(obj, dict):
        return obj.get(segment, _MISSING)
    return getattr(obj, segment, _MISSING)


def _descend_raw(obj: Any, segment: str | int) -> Any:
    """Descend one segment into the raw TOML AST; ``_MISSING`` if absent."""
    if isinstance(segment, int):
        if _has_index(obj, segment):
            return obj[segment]
        return _MISSING
    try:
        if segment in obj:
            return obj[segment]
    except TypeError:
        return _MISSING
    return _MISSING


def _has_index(obj: Any, index: int) -> bool:
    try:
        return 0 <= index < len(obj)
    except TypeError:
        return False


def _remap_to_config(segments: list[str | int]) -> list[str | int]:
    """Map a loader-shaped path onto :class:`ProjectConfig` attribute access.

    The ``[project]`` table is flattened onto top-level attributes (with
    ``name`` -> ``project_name``), and the ``[environments]`` table maps onto
    ``environment_overrides``. Every other segment maps by an identical name.
    """
    if not segments:
        return segments
    head = segments[0]
    if head == "project":
        rest = list(segments[1:])
        if rest and isinstance(rest[0], str):
            rest[0] = _PROJECT_FIELD_ALIASES.get(rest[0], rest[0])
        return rest
    if head == "environments":
        return ["environment_overrides", *segments[1:]]
    return list(segments)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temporary sibling and atomic rename."""
    directory = path.parent
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=directory,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_name = handle.name
    os.replace(tmp_name, path)
