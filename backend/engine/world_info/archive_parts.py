"""Bounded, integrity-checked ADS parts for large canonical knowledge corpora."""

import hashlib
import json
import re
import zipfile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from backend.engine import archive_safety
from backend.engine.world_info import limits

FORMAT = "TaleWeaverWorldInfoParts"
INLINE_LIMIT_BYTES = 4_194_304
MAX_PARTS = 128
KINDS = ("sources", "revisions", "entries")
Kind = Literal["sources", "revisions", "entries"]
_PATH = re.compile(r"^world-info/part-[0-9]{5}\.json$")


class WorldInfoArchiveError(ValueError):
    """A portable knowledge descriptor or part is invalid; never include its text."""


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class _Counts(_Contract):
    sources: StrictInt = Field(ge=0, le=limits.MAX_SOURCES)
    revisions: StrictInt = Field(ge=0, le=limits.MAX_SOURCES * limits.MAX_SOURCE_REVISIONS)
    entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)


class _Part(_Contract):
    path: str = Field(pattern=_PATH.pattern)
    kind: Kind
    bytes: StrictInt = Field(gt=0, lt=archive_safety.MAX_ENTRY_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rows: StrictInt = Field(gt=0, le=limits.MAX_SESSION_ENTRIES)


class _Descriptor(_Contract):
    format: Literal["TaleWeaverWorldInfoParts"]
    version: StrictInt = Field(ge=1, le=1)
    counts: _Counts
    parts: list[_Part] = Field(min_length=1, max_length=MAX_PARTS)


class _PartPayload(_Contract):
    version: StrictInt = Field(ge=1, le=1)
    kind: Kind
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=limits.MAX_SESSION_ENTRIES)


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _counts(corpus: dict[str, Any]) -> _Counts:
    if (
        set(corpus) != {"version", *KINDS}
        or type(corpus["version"]) is not int
        or corpus["version"] != 1
    ):
        raise WorldInfoArchiveError("World Info corpus structure is invalid.")
    if any(not isinstance(corpus[kind], list) for kind in KINDS):
        raise WorldInfoArchiveError("World Info corpus rows are invalid.")
    return _Counts.model_validate({kind: len(corpus[kind]) for kind in KINDS})


def _part_payload(kind: str, rows: list[bytes]) -> bytes:
    prefix = b'{"version":1,"kind":' + _json(kind) + b',"rows":['
    return prefix + b",".join(rows) + b"]}"


def _append_part(
    kind: str, rows: list[bytes], parts: list[tuple[str, bytes]], descriptors: list[dict]
) -> None:
    if len(parts) >= MAX_PARTS:
        raise WorldInfoArchiveError("World Info exceeds its archive part count budget.")
    payload = _part_payload(kind, rows)
    if len(payload) >= archive_safety.MAX_ENTRY_BYTES:
        raise WorldInfoArchiveError("World Info row exceeds the archive entry size budget.")
    path = f"world-info/part-{len(parts):05d}.json"
    parts.append((path, payload))
    descriptors.append(
        {
            "path": path,
            "kind": kind,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "rows": len(rows),
        }
    )


def _split_rows(
    kind: str, rows: list[dict], parts: list[tuple[str, bytes]], descriptors: list[dict]
) -> None:
    current: list[bytes] = []
    size = len(_part_payload(kind, []))
    for row in rows:
        if not isinstance(row, dict):
            raise WorldInfoArchiveError("World Info corpus rows are invalid.")
        encoded = _json(row)
        if current and size + len(encoded) + 1 > INLINE_LIMIT_BYTES:
            _append_part(kind, current, parts, descriptors)
            current = []
            size = len(_part_payload(kind, []))
        current.append(encoded)
        size += len(encoded) + (1 if len(current) > 1 else 0)
    if current:
        _append_part(kind, current, parts, descriptors)


def prepare_world_info(manifest: dict) -> tuple[dict, list[tuple[str, bytes]]]:
    """Keep small inline data unchanged; split complete rows without rewriting text."""
    corpus = manifest.get("world_info")
    if corpus is None or len(_json(corpus)) <= INLINE_LIMIT_BYTES:
        return manifest, []
    try:
        if not isinstance(corpus, dict):
            raise WorldInfoArchiveError("World Info corpus structure is invalid.")
        counts = _counts(corpus)
        parts: list[tuple[str, bytes]] = []
        descriptors: list[dict] = []
        for kind in KINDS:
            _split_rows(kind, corpus[kind], parts, descriptors)
        descriptor = _Descriptor.model_validate(
            {
                "format": FORMAT,
                "version": 1,
                "counts": counts.model_dump(),
                "parts": descriptors,
            }
        )
    except (ValidationError, UnicodeError, TypeError, RecursionError):
        raise WorldInfoArchiveError("World Info archive parts are invalid.") from None
    return {**manifest, "world_info": descriptor.model_dump()}, parts


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorldInfoArchiveError("World Info part contains duplicate object keys.")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise WorldInfoArchiveError("World Info part contains non-finite JSON values.")


def _read_part(archive: zipfile.ZipFile, part: _Part) -> list[dict]:
    info = archive.getinfo(part.path)
    if info.is_dir() or info.file_size != part.bytes:
        raise WorldInfoArchiveError("World Info archive part size is invalid.")
    with archive.open(info) as source:
        payload = source.read(part.bytes + 1)
    if len(payload) != part.bytes or hashlib.sha256(payload).hexdigest() != part.sha256:
        raise WorldInfoArchiveError("World Info archive part integrity check failed.")
    parsed = _PartPayload.model_validate(
        json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_keys, parse_constant=_nonfinite
        )
    )
    if parsed.kind != part.kind or len(parsed.rows) != part.rows:
        raise WorldInfoArchiveError("World Info archive part structure is invalid.")
    return parsed.rows


def read_world_info(archive: zipfile.ZipFile, section: Any) -> Any:
    """Resolve only declared local ZIP members under existing archive safety limits."""
    archive_safety.validate_archive(archive)
    members = {
        info.filename for info in archive.infolist() if info.filename.startswith("world-info/")
    }
    if not isinstance(section, dict) or section.get("format") != FORMAT:
        if members:
            raise WorldInfoArchiveError("World Info archive contains undeclared parts.")
        return section
    try:
        descriptor = _Descriptor.model_validate(section)
        expected = {part.path for part in descriptor.parts}
        if members != expected or len(expected) != len(descriptor.parts):
            raise WorldInfoArchiveError("World Info archive part membership is invalid.")
        corpus: dict[str, Any] = {"version": 1, **{kind: [] for kind in KINDS}}
        for index, part in enumerate(descriptor.parts):
            if part.path != f"world-info/part-{index:05d}.json":
                raise WorldInfoArchiveError("World Info archive part order is invalid.")
            corpus[part.kind].extend(_read_part(archive, part))
            if len(corpus[part.kind]) > getattr(descriptor.counts, part.kind):
                raise WorldInfoArchiveError("World Info archive row counts are invalid.")
        if {kind: len(corpus[kind]) for kind in KINDS} != descriptor.counts.model_dump():
            raise WorldInfoArchiveError("World Info archive row counts are invalid.")
        return corpus
    except (
        ValidationError,
        UnicodeError,
        TypeError,
        KeyError,
        RecursionError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ):
        raise WorldInfoArchiveError("World Info archive parts are invalid.") from None
