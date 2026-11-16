"""Strict, inert JSON and the notebook's canonical UTF-8 document quota."""

import json
import math
import re
from itertools import chain
from typing import Any, TypeAlias, cast

MAX_BYTES = 16_000_000
MAX_DEPTH = 64
MAX_NODES = 250_000
_TEXT_CHUNK_CHARS = 64 * 1024
_STRING_MARKER = re.compile(r'["\\]')
JsonValue: TypeAlias = bool | int | float | str | None | list["JsonValue"] | dict[str, "JsonValue"]


class NotebookError(ValueError):
    """A rejected local operation leaves the previously staged document intact."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _quota(size: int) -> None:
    if size > MAX_BYTES:
        raise NotebookError(
            "quota_exceeded", "Notebook exceeds its 16,000,000 canonical UTF-8 byte limit."
        )


def _structure(nodes: int, depth: int, extra_nodes: int = 0, extra_depth: int = 0) -> None:
    if nodes > MAX_NODES + extra_nodes or depth > MAX_DEPTH + extra_depth:
        raise NotebookError(
            "structure_limit", "Notebook exceeds its technical JSON depth or node limit."
        )


def _string_size(value: str) -> int:
    """Compute escaped UTF-8 bytes without allocating an expanded JSON string."""
    _quota(len(value) + 2)
    size = 2
    for start in range(0, len(value), _TEXT_CHUNK_CHARS):
        size += len(value[start : start + _TEXT_CHUNK_CHARS].encode("utf-8"))
        _quota(size)
    size += value.count('"') + value.count("\\")
    short = "\b\t\n\f\r"
    return size + sum(
        value.count(chr(code)) * (1 if chr(code) in short else 5) for code in range(32)
    )


def _scalar_size(value: Any) -> int:
    kind = type(value)
    if kind is str:
        return _string_size(value)
    if kind is float and not math.isfinite(value):
        raise NotebookError("invalid_json", "Notebook numbers must be finite.")
    if kind in {int, float}:
        return len(str(value))
    if kind is bool:
        return 4 if value else 5
    return 4


def _children(value: Any, visited: set[int]) -> tuple[Any, int, int]:
    if id(value) in visited:
        raise NotebookError(
            "invalid_json", "Notebook JSON must be a tree without shared containers."
        )
    visited.add(id(value))
    if type(value) is list:
        return iter(value), len(value), 2 + max(0, len(value) - 1)
    if any(type(key) is not str for key in value):
        raise NotebookError("invalid_json", "Notebook object keys must be strings.")
    return (
        chain(value.keys(), value.values()),
        2 * len(value),
        2 + max(0, len(value) - 1) + len(value),
    )


def _validate(value: Any) -> None:
    pending = [(value, 0)]
    visited: set[int] = set()
    nodes, size = 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        kind = type(item)
        if kind not in {type(None), bool, int, float, str, list, dict}:
            raise NotebookError("invalid_json", "Notebook values must use strict JSON types.")
        if kind not in {dict, list}:
            size += _scalar_size(item)
            _quota(size)
            continue
        children, count, punctuation = _children(item, visited)
        _structure(nodes + len(pending) + count, depth + 1)
        size += punctuation
        _quota(size)
        pending.extend((child, depth + 1) for child in children)


def _encode(value: JsonValue) -> bytes:
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    result = bytearray()
    for fragment in encoder.iterencode(value):
        encoded = fragment.encode("utf-8")
        _quota(len(result) + len(encoded))
        result.extend(encoded)
    return bytes(result)


def encode(value: JsonValue) -> bytes:
    """Sort object keys; preserve string contents; count the resulting UTF-8 bytes."""
    try:
        _validate(value)
        return _encode(value)
    except NotebookError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise NotebookError("invalid_json", "Notebook document cannot be encoded as JSON.") from exc


def _raw_structure(text: str, extra_nodes: int = 0, extra_depth: int = 0) -> None:
    """Count raw JSON values/keys before the parser allocates their containers."""
    nodes, depth = 0, 0
    index, atom = 0, False
    while index < len(text):
        character = text[index]
        if character == '"':
            nodes += 1
            _structure(nodes, depth, extra_nodes, extra_depth)
            index, atom = _string_end(text, index + 1), False
            continue
        elif character in "[{":
            nodes, depth = nodes + 1, depth + 1
        elif character in "]}":
            depth -= 1
        elif character not in " \t\r\n,:" and not atom:
            nodes += 1
        atom = character not in ' \t\r\n,:{}[]"'
        _structure(nodes, depth, extra_nodes, extra_depth)
        index += 1


def _string_end(text: str, index: int) -> int:
    """Skip inert string contents in C-sized spans rather than one Python call per byte."""
    while marker := _STRING_MARKER.search(text, index):
        if marker.group() == '"':
            return marker.end()
        index = marker.end() + 1
    return len(text)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NotebookError("invalid_json", "Notebook JSON contains a duplicate object key.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise NotebookError("invalid_json", "Notebook numbers must be finite.")


def _allowance(value: int, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise NotebookError("invalid_argument", "Notebook JSON envelope allowance is invalid.")
    return value


def preflight(
    raw: bytes | str,
    *,
    extra_depth: int = 0,
    extra_nodes: int = 0,
    max_transport_bytes: int | None = None,
) -> str:
    """Bound raw structure before parsing; trusted envelopes may add 8 levels/256 nodes.

    This checks UTF-8 and resource limits, not JSON syntax or duplicate keys.
    The caller must still use a strict parser and validate the inner document.
    """
    if type(raw) not in {bytes, str}:
        raise NotebookError("invalid_json", "Notebook JSON must be text or UTF-8 bytes.")
    extra_depth, extra_nodes = _allowance(extra_depth, 8), _allowance(extra_nodes, 256)
    try:
        _transport_size(raw, max_transport_bytes)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        _raw_structure(text, extra_nodes, extra_depth)
        return text
    except UnicodeError as exc:
        raise NotebookError("invalid_json", "Notebook document is not valid UTF-8 JSON.") from exc


def _transport_limit(size: int, limit: int | None) -> None:
    if limit is not None and size > limit:
        raise NotebookError("quota_exceeded", "Notebook JSON transport exceeds its byte limit.")


def _transport_size(raw: bytes | str, limit: int | None) -> None:
    if limit is not None and (type(limit) is not int or limit < 1):
        raise NotebookError("invalid_argument", "Notebook JSON transport limit is invalid.")
    _transport_limit(len(raw), limit)
    if isinstance(raw, bytes):
        return
    size = 0
    for start in range(0, len(raw), _TEXT_CHUNK_CHARS):
        size += len(raw[start : start + _TEXT_CHUNK_CHARS].encode("utf-8"))
        _transport_limit(size, limit)


def document(raw: bytes | str) -> tuple[JsonValue, bytes]:
    """Parse raw JSON before duplicate keys or invalid numbers can be discarded."""
    try:
        text = preflight(raw)
        value = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    except NotebookError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise NotebookError("invalid_json", "Notebook document is not valid UTF-8 JSON.") from exc
    value = cast(JsonValue, value)
    return value, encode(value)


def decode(raw: bytes | str) -> JsonValue:
    """Return a validated JSON value; the same document quota applies on load."""
    return document(raw)[0]


def canonicalize(raw: bytes | str) -> bytes:
    """Normalize JSON transport whitespace without changing any string content."""
    return document(raw)[1]
