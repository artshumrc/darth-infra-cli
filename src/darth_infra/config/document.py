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

import copy
import difflib
import hashlib
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator

import tomlkit
from tomlkit import TOMLDocument

from .loader import _parse_project
from .models import ProjectConfig

__all__ = [
    "ProjectDocument",
    "ValidationResult",
    "DocumentConflictError",
    "DocumentValidationError",
    "ChangeOperation",
    "SemanticChange",
    "MergeConflict",
    "MergeResult",
    "DraftTransaction",
    "ABSENT",
    "diff_documents",
    "three_way_merge",
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


class _Absent:
    """Singleton sentinel meaning "no value is present at this path".

    Distinct from ``None`` (TOML has no null): a semantic change or merge input
    is *absent* when the field/record does not exist at all, which is different
    from an explicit value that happens to be ``None`` in the model.
    """

    _instance: _Absent | None = None

    def __new__(cls) -> _Absent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "ABSENT"

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return False


ABSENT = _Absent()


# Semantic identity of the repeated collections, keyed by their *wildcard* path
# (``[]`` marks each object element of a parent array). Records are matched by
# these keys across documents so that reordering a collection does not make its
# members look changed, and so a member edited on disk can be reconciled with the
# same member edited in the draft. Connections carry a composite identity derived
# from their declared keys because they have no single name field. This mirrors
# the identities named in the persisted schema; it deliberately lives here rather
# than importing the TUI field registry so the config layer stays independent of
# the editor layer.
_IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "services": ("name",),
    "secrets": ("name",),
    "s3_buckets": ("name",),
    "alb.path_rules": ("name",),
    "cloudfront.cached_behaviors": ("name",),
    "cloudfront.connections": ("service", "env_key"),
    "services[].ulimits": ("name",),
    "services[].ebs_volumes": ("name",),
    "s3_buckets[].connections": ("service", "env_key"),
}

# Wildcard paths of tables whose keys are arbitrary (maps), as opposed to fixed
# schema fields. Their entries are add/remove/change values with no default, so
# they are never classified as "reset to default". ``environments`` is a map of
# override *objects*; the rest are maps of scalars. These correspond to every
# ``.*`` segment in the persisted schema/field registry.
_MAP_TABLES: frozenset[str] = frozenset(
    {
        "environments",
        "environments.*.tags",
        "environments.*.ec2_instance_type_override",
        "project.tags",
        "services[].environment_variables",
        "preview_environments.tags",
    }
)

# Path token: an identity/index selector in brackets or a bare key segment.
_SEMANTIC_TOKEN_RE = re.compile(r"\[([^\]]*)\]|([^.\[\]]+)")


class ChangeOperation(str, Enum):
    """The kind of a single semantic change between two documents."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    RESET_TO_DEFAULT = "reset_to_default"


@dataclass(frozen=True)
class SemanticChange:
    """One semantic change at a stable identity path.

    Attributes:
        path: Identity-based semantic path, e.g. ``services[name=web].cpu``.
        operation: Which of add / remove / change / reset-to-default occurred.
        before: The baseline value, or :data:`ABSENT` for an addition.
        after: The draft value, or :data:`ABSENT` for a removal. For a
            reset-to-default this is the effective default the field falls back
            to once its explicit key is gone.
    """

    path: str
    operation: ChangeOperation
    before: Any
    after: Any


@dataclass(frozen=True)
class MergeConflict:
    """A field that both the disk and the draft changed incompatibly.

    Carries all three sides so the caller can present an explicit choice. Any
    side may be :data:`ABSENT` (for example a record deleted on one side and
    modified on the other).
    """

    path: str
    baseline: Any
    disk: Any
    draft: Any


@dataclass(frozen=True)
class MergeResult:
    """The outcome of a three-way merge.

    ``merged_text`` is the reconciled document text when the merge is clean;
    it is ``None`` when there are conflicts. ``validation`` reports whether the
    merged document still satisfies model semantics. ``ok`` is true only when
    there are no conflicts and the merged document validates.
    """

    conflicts: list[MergeConflict]
    merged_text: str | None
    validation: ValidationResult | None
    disk_text: str
    disk_revision: str

    @property
    def ok(self) -> bool:
        if self.conflicts or self.merged_text is None:
            return False
        return self.validation is None or self.validation.ok


@dataclass
class _DocModel:
    """A document flattened to identity-keyed leaves for diffing and merging."""

    leaves: dict[str, Any]
    map_entries: set[str]
    record_paths: set[str]


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

    def raw_value(self, field_path: str) -> Any:
        """Return the raw persisted value at ``field_path`` without the model.

        Unlike :meth:`value`, this never constructs :class:`ProjectConfig`, so it
        works even when a *different* part of the draft is temporarily invalid
        (for example a half-entered repeated record). It returns the explicitly
        persisted value unwrapped to plain Python, or ``None`` when the key is
        absent. It does not compute effective defaults.
        """
        node = _resolve_node(self._doc, _parse_path(field_path))
        if node is _MISSING:
            return None
        unwrap = getattr(node, "unwrap", None)
        value = unwrap() if callable(unwrap) else node
        return _unwrap_enum(value)

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

    # -- repeated collections ----------------------------------------------

    def record_count(self, collection_path: str) -> int:
        """Return the number of records in the array-of-tables at ``collection_path``.

        Reports raw-document presence (not model semantics) so a draft that is
        temporarily invalid still reports how many records the editor is holding.
        Returns ``0`` when the collection is absent.
        """
        node = _resolve_node(self._doc, _parse_path(collection_path))
        if node is _MISSING:
            return 0
        try:
            return len(node)
        except TypeError:
            return 0

    def raw_record(self, collection_path: str, index: int) -> dict[str, Any]:
        """Return a plain-``dict`` copy of one record's explicitly-present keys.

        The result contains only keys the document actually holds (omitted
        defaults are absent), with nested tables/arrays unwrapped to plain
        Python. It is a detached copy: mutating it does not affect the draft.
        Returns an empty dict when the record does not exist.
        """
        node = _resolve_node(self._doc, _parse_path(collection_path))
        if node is _MISSING or not _has_index(node, index):
            return {}
        return node[index].unwrap()

    def add_record(
        self, collection_path: str, values: dict[str, Any] | None = None
    ) -> int:
        """Append a new record to the array-of-tables at ``collection_path``.

        Creates the array-of-tables when it does not exist yet. Only the keys in
        ``values`` are written, so the new record starts minimal and every other
        field remains omitted at its schema default. Returns the new record's
        index.
        """
        segments = _parse_path(collection_path)
        parent = self._resolve_container(segments[:-1], create=True)
        key = segments[-1]
        if not isinstance(key, str):
            raise ValueError(
                f"cannot add a record at array index {key!r}; "
                "collection_path must end in a table key"
            )
        if key not in parent:
            parent[key] = tomlkit.aot()
        aot = parent[key]
        table = tomlkit.table()
        for name, value in (values or {}).items():
            table[name] = value
        aot.append(table)
        self._invalidate()
        return len(aot) - 1

    def remove_record(self, collection_path: str, index: int) -> None:
        """Remove the record at ``index`` from ``collection_path``.

        A missing collection or out-of-range index is a no-op.
        """
        segments = _parse_path(collection_path)
        parent = self._resolve_container(segments[:-1], create=False)
        if parent is _MISSING:
            return
        key = segments[-1]
        try:
            aot = parent[key]
        except (KeyError, TypeError):
            return
        if _has_index(aot, index):
            del aot[index]
            self._invalidate()

    # -- reversion ---------------------------------------------------------

    def revert_field(self, field_path: str) -> None:
        """Restore one field to the session baseline's value and presence.

        Restores the baseline value, its explicit-versus-omitted presence, and
        any comment attached to the field. A field the baseline omitted is
        removed from the draft rather than written at its default.
        """
        self._revert_path(field_path)

    def revert_section(self, section_path: str) -> None:
        """Restore a whole container (table or record) to the session baseline.

        ``section_path`` addresses a table or array element, for example
        ``"project"``, ``"alb"``, or ``"services[0]"``. Every field beneath it is
        restored to the baseline's value, presence, and comments together.
        """
        self._revert_path(section_path)

    def revert_all(self) -> None:
        """Restore the entire draft to the session baseline, comments and all."""
        self._doc = tomlkit.parse(self._baseline_text)
        self._invalidate()

    def _revert_path(self, path: str) -> None:
        baseline_doc = tomlkit.parse(self._baseline_text)
        segments = _parse_path(path)
        base_node = _resolve_node(baseline_doc, segments)
        parent = self._resolve_container(
            segments[:-1], create=base_node is not _MISSING
        )
        if parent is _MISSING:
            return
        last = segments[-1]
        if base_node is not _MISSING:
            # Splicing a deep-copied baseline node restores value + trivia
            # (trailing comments live on the node itself).
            parent[last] = copy.deepcopy(base_node)
            self._invalidate()
        elif _container_has(parent, last):
            del parent[last]
            self._invalidate()

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[DraftTransaction]:
        """Group a set of draft edits into one atomic, reversible unit.

        Edits performed inside the block apply together. If the block raises,
        the draft is rolled back to its state before the block, so a failed
        cascading edit never leaves partial changes. The yielded handle can
        later ``revert()`` the transaction as a whole, undoing exactly its
        edits while preserving edits made before it. Nothing is persisted; this
        is in-memory only.
        """
        snapshot = self.to_toml()
        txn = DraftTransaction(self, snapshot)
        try:
            yield txn
        except BaseException:
            self._restore_text(snapshot)
            raise

    def _restore_text(self, text: str) -> None:
        self._doc = tomlkit.parse(text)
        self._invalidate()

    # -- semantic diff -----------------------------------------------------

    def semantic_changes(self) -> list[SemanticChange]:
        """Classify the draft's changes against the session baseline.

        Returns one :class:`SemanticChange` per changed field or record, using
        stable identity paths so collection reordering produces no changes.
        This is separate from :meth:`toml_patch`, which reports the exact text.
        """
        return diff_documents(self._baseline_text, self.to_toml())

    # -- three-way merge ---------------------------------------------------

    def merge_with_disk(self) -> MergeResult:
        """Merge the baseline, the current disk document, and the draft.

        Compares all three at semantic field paths. Disjoint changes merge
        automatically, preserving both documents' unrelated formatting and
        comments. Fields changed incompatibly on both sides are returned as
        conflicts. This never mutates the draft; call :meth:`adopt_merge` to
        take a clean result.
        """
        disk_text = self._path.read_text()
        return three_way_merge(self._baseline_text, disk_text, self.to_toml())

    def adopt_merge(self, result: MergeResult) -> None:
        """Adopt a clean, validated merge as the current draft and baseline.

        Raises:
            ValueError: The result still has unresolved conflicts.
            DocumentValidationError: The merged document fails model validation.
        """
        if result.conflicts:
            raise ValueError(
                "cannot adopt a merge with unresolved conflicts; resolve them "
                "first"
            )
        if result.merged_text is None:
            raise ValueError("merge produced no reconciled document")
        if result.validation is not None and not result.validation.ok:
            raise DocumentValidationError(
                result.validation.error or "merged configuration is invalid"
            )
        self._doc = tomlkit.parse(result.merged_text)
        self._baseline_text = result.disk_text
        self._revision = result.disk_revision
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


class DraftTransaction:
    """Handle for a group of draft edits made inside :meth:`ProjectDocument.transaction`.

    A cascading edit (for example deleting a resource and cleaning up every
    reference to it) is one transaction. ``revert`` undoes exactly the edits made
    within the transaction, restoring the draft to its state just before the
    block, without disturbing edits made earlier in the session.
    """

    def __init__(self, document: ProjectDocument, snapshot: str) -> None:
        self._document = document
        self._snapshot = snapshot

    def revert(self) -> None:
        """Undo every edit made within this transaction, together."""
        self._document._restore_text(self._snapshot)


# ---------------------------------------------------------------------------
# Semantic diff and three-way merge (pure, text-in / structured-out).
# ---------------------------------------------------------------------------


def diff_documents(baseline_text: str, draft_text: str) -> list[SemanticChange]:
    """Classify the semantic changes from ``baseline_text`` to ``draft_text``.

    Records are matched by identity, so reordering a collection produces no
    changes. A whole added or removed record is reported as a single change;
    fields of records present in both sides are reported individually.
    """
    base_plain = tomlkit.parse(baseline_text).unwrap()
    draft_plain = tomlkit.parse(draft_text).unwrap()
    base = _flatten(base_plain)
    draft = _flatten(draft_plain)

    changes: list[SemanticChange] = []

    top_added = _top_level_records(draft.record_paths - base.record_paths)
    top_removed = _top_level_records(base.record_paths - draft.record_paths)
    for record in sorted(top_added):
        changes.append(
            SemanticChange(
                record,
                ChangeOperation.ADDED,
                ABSENT,
                _navigate_plain(draft_plain, record),
            )
        )
    for record in sorted(top_removed):
        changes.append(
            SemanticChange(
                record,
                ChangeOperation.REMOVED,
                _navigate_plain(base_plain, record),
                ABSENT,
            )
        )

    draft_config: Any = _MISSING
    for path in sorted(set(base.leaves) | set(draft.leaves)):
        if _under_any(path, top_added) or _under_any(path, top_removed):
            continue
        before = base.leaves.get(path, ABSENT)
        after = draft.leaves.get(path, ABSENT)
        if _eq(before, after):
            continue
        if before is ABSENT:
            changes.append(SemanticChange(path, ChangeOperation.ADDED, ABSENT, after))
        elif after is ABSENT:
            if path in base.map_entries or path in draft.map_entries:
                changes.append(
                    SemanticChange(path, ChangeOperation.REMOVED, before, ABSENT)
                )
            else:
                if draft_config is _MISSING:
                    draft_config = _try_parse(draft_plain)
                default = (
                    _effective_value(draft_config, path)
                    if draft_config is not None
                    else ABSENT
                )
                changes.append(
                    SemanticChange(
                        path, ChangeOperation.RESET_TO_DEFAULT, before, default
                    )
                )
        else:
            changes.append(SemanticChange(path, ChangeOperation.CHANGED, before, after))
    return changes


def three_way_merge(
    baseline_text: str, disk_text: str, draft_text: str
) -> MergeResult:
    """Reconcile a common ``baseline`` with independent ``disk`` and ``draft`` edits.

    Compares all three at identity-keyed field paths. Where only one side moved
    away from the baseline, that side wins; where both moved to the same value,
    there is no conflict; where both moved to different values (including a
    delete on one side and a modify on the other) a :class:`MergeConflict` is
    reported and no merged text is produced. A clean merge is built on top of the
    disk document so the external edits' formatting is preserved, with the
    draft's changes spliced in to preserve theirs. The merged document is
    revalidated before it is offered for saving.
    """
    disk_doc = tomlkit.parse(disk_text)
    draft_doc = tomlkit.parse(draft_text)
    base = _flatten(tomlkit.parse(baseline_text).unwrap())
    disk = _flatten(disk_doc.unwrap())
    draft = _flatten(draft_doc.unwrap())
    disk_revision = _hash(disk_text)

    conflicts: list[MergeConflict] = []
    draft_wins: dict[str, Any] = {}
    for path in set(base.leaves) | set(disk.leaves) | set(draft.leaves):
        b = base.leaves.get(path, ABSENT)
        d = disk.leaves.get(path, ABSENT)
        r = draft.leaves.get(path, ABSENT)
        if _eq(d, r):
            continue
        if _eq(d, b):
            draft_wins[path] = r
        elif _eq(r, b):
            continue
        else:
            conflicts.append(MergeConflict(path, b, d, r))

    if conflicts:
        conflicts.sort(key=lambda c: c.path)
        return MergeResult(
            conflicts=conflicts,
            merged_text=None,
            validation=None,
            disk_text=disk_text,
            disk_revision=disk_revision,
        )

    merged = copy.deepcopy(disk_doc)
    _apply_draft_wins(merged, draft_doc, draft_wins, base, disk, draft)
    merged_text = tomlkit.dumps(merged)
    return MergeResult(
        conflicts=[],
        merged_text=merged_text,
        validation=_validate_text(merged_text),
        disk_text=disk_text,
        disk_revision=disk_revision,
    )


# -- flattening a document to identity-keyed leaves --------------------------


def _flatten(plain: Any) -> _DocModel:
    """Flatten a plain (unwrapped) document to identity-keyed leaves."""
    model = _DocModel(leaves={}, map_entries=set(), record_paths=set())
    _walk(plain, "", "", model)
    return model


def _walk(value: Any, sem: str, wild: str, model: _DocModel) -> None:
    if isinstance(value, dict):
        is_map = wild in _MAP_TABLES
        for key, child in value.items():
            child_sem = f"{sem}.{key}" if sem else key
            if is_map:
                child_wild = f"{wild}.*"
            elif wild:
                child_wild = f"{wild}.{key}"
            else:
                child_wild = key
            _walk(child, child_sem, child_wild, model)
        return
    if isinstance(value, list):
        keys = _IDENTITY_KEYS.get(wild)
        if keys is not None:
            for index, element in enumerate(value):
                ident = _identity_string(
                    element if isinstance(element, dict) else {}, keys, index
                )
                record_sem = f"{sem}[{ident}]"
                model.record_paths.add(record_sem)
                _walk(element, record_sem, f"{wild}[]", model)
            return
        # Array of scalars: one leaf whose value is the whole list.
        model.leaves[sem] = value
        return
    model.leaves[sem] = value
    if wild.endswith(".*"):
        model.map_entries.add(sem)


def _identity_string(
    element: dict[str, Any], keys: tuple[str, ...], index: int
) -> str:
    parts = []
    for key in keys:
        if key not in element:
            return f"#{index}"
        parts.append(f"{key}={element[key]}")
    return ",".join(parts)


# -- semantic path parsing and navigation -----------------------------------


def _semantic_tokens(sem_path: str) -> list[Any]:
    """Split a semantic path into key strings and record selectors.

    A selector is a dict of identity keys (``{"name": "web"}``) or an
    index fallback (``{"__index__": 0}``) for records missing an identity.
    """
    tokens: list[Any] = []
    for match in _SEMANTIC_TOKEN_RE.finditer(sem_path):
        bracket, key = match.group(1), match.group(2)
        if bracket is not None:
            if bracket.startswith("#"):
                tokens.append({"__index__": int(bracket[1:])})
            else:
                selector: dict[str, str] = {}
                for pair in bracket.split(","):
                    name, _, val = pair.partition("=")
                    selector[name] = val
                tokens.append(selector)
        else:
            tokens.append(key)
    return tokens


def _navigate_plain(plain: Any, sem_path: str) -> Any:
    obj = plain
    for token in _semantic_tokens(sem_path):
        if obj is None:
            return None
        if isinstance(token, dict):
            obj = _find_plain_record(obj, token)
        elif isinstance(obj, dict):
            obj = obj.get(token)
        else:
            return None
    return obj


def _find_plain_record(collection: Any, selector: dict[str, Any]) -> Any:
    if not isinstance(collection, list):
        return None
    if "__index__" in selector:
        index = selector["__index__"]
        return collection[index] if 0 <= index < len(collection) else None
    for element in collection:
        if isinstance(element, dict) and _matches(element, selector):
            return element
    return None


def _matches(element: dict[str, Any], selector: dict[str, Any]) -> bool:
    return all(str(element.get(key)) == value for key, value in selector.items())


# -- record roll-up helpers -------------------------------------------------


def _is_ancestor(ancestor: str, path: str) -> bool:
    return (
        path != ancestor
        and path.startswith(ancestor)
        and path[len(ancestor)] in ".["
    )


def _top_level_records(records: set[str]) -> set[str]:
    """Keep only records that are not nested inside another record in the set."""
    return {
        record
        for record in records
        if not any(_is_ancestor(other, record) for other in records if other != record)
    }


def _under_any(path: str, records: set[str]) -> bool:
    return any(path == record or _is_ancestor(record, path) for record in records)


# -- value comparison and effective-default resolution ----------------------


def _eq(left: Any, right: Any) -> bool:
    if left is ABSENT or right is ABSENT:
        return left is ABSENT and right is ABSENT
    return left == right


def _try_parse(plain: Any) -> ProjectConfig | None:
    try:
        return _parse_project(plain)
    except (ValueError, KeyError, TypeError):
        return None


def _validate_text(text: str) -> ValidationResult:
    try:
        _parse_project(tomlkit.parse(text).unwrap())
    except (ValueError, KeyError, TypeError) as exc:
        return ValidationResult(ok=False, error=str(exc))
    return ValidationResult(ok=True)


def _effective_value(config: ProjectConfig, sem_path: str) -> Any:
    """Resolve the effective model value at a semantic path, or ABSENT."""
    tokens = _semantic_tokens(sem_path)
    if tokens and tokens[0] == "project":
        tokens = tokens[1:]
        if tokens and isinstance(tokens[0], str):
            tokens[0] = _PROJECT_FIELD_ALIASES.get(tokens[0], tokens[0])
    elif tokens and tokens[0] == "environments":
        tokens = ["environment_overrides", *tokens[1:]]
    obj: Any = config
    for token in tokens:
        if obj is None:
            return None
        if isinstance(token, dict):
            obj = _find_model_record(obj, token)
            if obj is None:
                return ABSENT
        else:
            obj = _descend_model(obj, token)
            if obj is _MISSING:
                return ABSENT
    return _unwrap_enum(obj)


def _find_model_record(collection: Any, selector: dict[str, Any]) -> Any:
    if not isinstance(collection, (list, tuple)):
        return None
    if "__index__" in selector:
        index = selector["__index__"]
        return collection[index] if 0 <= index < len(collection) else None
    for element in collection:
        if all(
            str(_unwrap_enum(getattr(element, key, None))) == value
            for key, value in selector.items()
        ):
            return element
    return None


# -- applying draft changes onto the disk-based merged document --------------


def _apply_draft_wins(
    merged: TOMLDocument,
    draft_doc: TOMLDocument,
    draft_wins: dict[str, Any],
    base: _DocModel,
    disk: _DocModel,
    draft: _DocModel,
) -> None:
    top_added = _top_level_records(draft.record_paths - base.record_paths)
    top_removed = _top_level_records(base.record_paths - draft.record_paths)

    for record in top_added:
        if record not in disk.record_paths:
            _splice_record(merged, draft_doc, record)
    for record in top_removed:
        if record in disk.record_paths:
            _remove_record(merged, record)

    for path, value in draft_wins.items():
        if _under_any(path, top_added) or _under_any(path, top_removed):
            continue
        _apply_leaf(merged, draft_doc, path, value)


def _navigate_toml(
    container: Any, tokens: list[Any], *, create: bool = False, create_aot: bool = False
) -> Any:
    obj = container
    for index, token in enumerate(tokens):
        is_last = index == len(tokens) - 1
        if isinstance(token, dict):
            record_index = _find_index_toml(obj, token)
            if record_index is None:
                return _MISSING
            obj = obj[record_index]
        elif token in obj:
            obj = obj[token]
        elif create or create_aot:
            obj[token] = tomlkit.aot() if (create_aot and is_last) else tomlkit.table()
            obj = obj[token]
        else:
            return _MISSING
    return obj


def _find_index_toml(collection: Any, selector: dict[str, Any]) -> int | None:
    try:
        length = len(collection)
    except TypeError:
        return None
    if "__index__" in selector:
        index = selector["__index__"]
        return index if 0 <= index < length else None
    for index in range(length):
        element = collection[index]
        if all(str(element.get(key)) == value for key, value in selector.items()):
            return index
    return None


def _splice_record(merged: TOMLDocument, draft_doc: TOMLDocument, record: str) -> None:
    tokens = _semantic_tokens(record)
    draft_node = _navigate_toml(draft_doc, tokens)
    if draft_node is _MISSING:
        return
    collection = _navigate_toml(merged, tokens[:-1], create_aot=True)
    if collection is _MISSING:
        return
    collection.append(copy.deepcopy(draft_node))


def _remove_record(merged: TOMLDocument, record: str) -> None:
    tokens = _semantic_tokens(record)
    collection = _navigate_toml(merged, tokens[:-1])
    if collection is _MISSING:
        return
    index = _find_index_toml(collection, tokens[-1])
    if index is not None:
        del collection[index]


def _apply_leaf(
    merged: TOMLDocument, draft_doc: TOMLDocument, path: str, value: Any
) -> None:
    tokens = _semantic_tokens(path)
    parent = _navigate_toml(merged, tokens[:-1], create=True)
    if parent is _MISSING:
        return
    key = tokens[-1]
    if value is ABSENT:
        if _container_has(parent, key):
            del parent[key]
        return
    draft_node = _navigate_toml(draft_doc, tokens)
    parent[key] = copy.deepcopy(draft_node) if draft_node is not _MISSING else value


# -- shared low-level accessors ---------------------------------------------


def _resolve_node(container: Any, segments: list[str | int]) -> Any:
    """Resolve an index/key path against a raw TOML doc; ``_MISSING`` if absent."""
    obj = container
    for segment in segments:
        child = _descend_raw(obj, segment)
        if child is _MISSING:
            return _MISSING
        obj = child
    return obj


def _container_has(container: Any, key: str | int) -> bool:
    try:
        if isinstance(key, int):
            return 0 <= key < len(container)
        return key in container
    except TypeError:
        return False
