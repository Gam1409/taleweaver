"""File-backed, integrity checked portable notebook payload parts."""

import hashlib
import json
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from backend.engine import archive_safety
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook.codec import MAX_BYTES, preflight
from backend.engine.chpm.notebook_store import MAX_CORPUS_BYTES, MAX_NOTEBOOKS

KEY = "npc_notebooks"
FORMAT = "TaleWeaverNpcNotebookParts"
PART_BYTES = 16 * 1024 * 1024
MAX_PARTS = MAX_NOTEBOOKS


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    path: str = Field(pattern=r"^npc-notebooks/part-[0-9]{5}\.json$")
    bytes: StrictInt = Field(gt=0, le=PART_BYTES + 4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rows: StrictInt = Field(ge=1, le=1)


class _Descriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    format: str = Field(pattern=f"^{FORMAT}$")
    version: StrictInt = Field(ge=1, le=1)
    rows: StrictInt = Field(ge=1, le=MAX_NOTEBOOKS)
    parts: list[_Part] = Field(min_length=1, max_length=MAX_PARTS)


@dataclass
class NotebookArchive:
    stream: Any
    parts: list[dict]
    offsets: list[int]
    rows: int

    def descriptor(self) -> dict:
        return {"format": FORMAT, "version": 1, "rows": self.rows, "parts": self.parts}

    def payloads(self) -> Iterator[tuple[str, bytes]]:
        for part, offset in zip(self.parts, self.offsets, strict=True):
            self.stream.seek(offset)
            yield part["path"], self.stream.read(part["bytes"])


def _encoded(row: dict, payload: bytes) -> bytes:
    meta = json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return meta[:-1] + b',"document":' + payload + b"}"


def create_archive() -> NotebookArchive:
    return NotebookArchive(tempfile.SpooledTemporaryFile(max_size=1024 * 1024), [], [], 0)


def append_part(corpus: NotebookArchive, rows: list[bytes]) -> None:
    if len(rows) != 1:
        raise ChpmError("A notebook archive part must contain exactly one NPC document.")
    if len(corpus.parts) >= MAX_PARTS:
        raise ChpmError("Notebook corpus exceeds its archive part budget.")
    payload = b"[" + b",".join(rows) + b"]"
    _store_part(corpus, payload, len(rows))


def _store_part(corpus: NotebookArchive, payload: bytes, count: int) -> None:
    offset = corpus.stream.tell()
    corpus.stream.write(payload)
    corpus.offsets.append(offset)
    corpus.parts.append(
        {
            "path": f"npc-notebooks/part-{len(corpus.parts):05d}.json",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "rows": count,
        }
    )
    corpus.rows += count


def prepare_notebooks(manifest: dict) -> tuple[dict, Any]:
    section = manifest.get(KEY)
    if section is None:
        return manifest, ()
    if not isinstance(section, NotebookArchive):
        raise ChpmError("Notebook portable corpus is invalid.")
    return {**manifest, KEY: section.descriptor()}, section.payloads()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ChpmError("Notebook archive contains duplicate object keys.")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ChpmError("Notebook archive contains non-finite JSON values.")


def rows(payload: bytes) -> list[dict]:
    text = preflight(payload, extra_depth=2, extra_nodes=16, max_transport_bytes=MAX_BYTES + 1024)
    parsed = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(parsed, list) or len(parsed) != 1:
        raise ChpmError("Notebook archive part is invalid.")
    return parsed


def _read_part(archive: Any, part: _Part) -> tuple[bytes, int]:
    info = archive.getinfo(part.path)
    if info.is_dir() or info.file_size != part.bytes:
        raise ChpmError("Notebook archive part size is invalid.")
    payload = archive.read(part.path)
    if hashlib.sha256(payload).hexdigest() != part.sha256:
        raise ChpmError("Notebook archive part integrity check failed.")
    parsed = rows(payload)
    if len(parsed) != part.rows:
        raise ChpmError("Notebook archive part count is invalid.")
    return payload, len(parsed)


def read_notebooks(archive: Any, section: Any) -> NotebookArchive | None:
    archive_safety.validate_archive(archive)
    members = {name for name in archive.namelist() if name.startswith("npc-notebooks/")}
    if section is None and not members:
        return None
    try:
        descriptor = _Descriptor.model_validate(section)
    except ValidationError:
        raise ChpmError("Notebook archive descriptor is invalid.") from None
    corpus = create_archive()
    try:
        _read_members(archive, descriptor, corpus, members)
        return corpus
    except BaseException:
        corpus.stream.close()
        raise


def _read_members(
    archive: Any, descriptor: _Descriptor, corpus: NotebookArchive, members: set[str]
) -> None:
    total = 0
    for index, part in enumerate(descriptor.parts):
        path = f"npc-notebooks/part-{index:05d}.json"
        if part.path != path:
            raise ChpmError("Notebook archive part order is invalid.")
        payload, count = _read_part(archive, part)
        total += len(payload)
        if total > MAX_CORPUS_BYTES + MAX_NOTEBOOKS * 4096 or corpus.rows + count > MAX_NOTEBOOKS:
            raise ChpmError("Notebook archive corpus exceeds its budget.")
        _store_part(corpus, payload, count)
    if members != {part.path for part in descriptor.parts} or descriptor.rows != corpus.rows:
        raise ChpmError("Notebook archive membership or row count is invalid.")
