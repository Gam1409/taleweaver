"""One detached NPC notebook draft; no database, world-state or execution access."""

import json
from typing import Any

from backend.engine.chpm.notebook import tree
from backend.engine.chpm.notebook.codec import JsonValue, NotebookError, decode, document, encode

DEFAULT_READ_CHARS = 1400
MIN_READ_CHARS = 256
MAX_READ_CHARS = 4096


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise NotebookError("invalid_argument", f"Notebook {name} must be a nonnegative integer.")
    return value


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _kind(value: JsonValue) -> str:
    names = {dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null"}
    return names.get(type(value), "number")


class NotebookWorkspace:
    """Reads share the base tree; edits clone only changed paths until atomic acceptance."""

    def __init__(self, base_bytes: bytes = b"{}", revision: int = 0) -> None:
        self._revision = _integer(revision, "revision")
        self._base_revision = self._revision
        self._value, self._bytes = document(base_bytes)
        self._base_bytes = self._bytes

    @property
    def base_revision(self) -> int:
        """The immutable persisted revision against which the host commits this draft."""
        return self._base_revision

    @property
    def revision(self) -> int:
        """The staged revision used to order local reads and mutations."""
        return self._revision

    @property
    def canonical_bytes(self) -> bytes:
        return self._bytes

    @property
    def byte_size(self) -> int:
        return len(self._bytes)

    @property
    def changed(self) -> bool:
        return self._bytes != self._base_bytes

    def read(self, pointer: str = "", *, offset: int = 0, limit: int = DEFAULT_READ_CHARS) -> dict:
        """Page serialized JSON; limit covers escaped fragments and all response metadata."""
        offset = _integer(offset, "read offset")
        limit = _integer(limit, "read limit")
        if not MIN_READ_CHARS <= limit <= MAX_READ_CHARS:
            raise NotebookError(
                "invalid_argument", "Notebook read limit must be 256–4096 characters."
            )
        selected = tree.lookup(self._value, pointer)
        text = (self._bytes if not pointer else encode(selected)).decode("utf-8")
        if offset > len(text):
            raise NotebookError("invalid_argument", "Notebook read offset exceeds this JSON value.")
        result = {
            "status": "ok",
            "revision": self.revision,
            "byte_size": self.byte_size,
            "type": _kind(selected),
            "offset": offset,
            "next_offset": None,
            "total_chars": len(text),
            "complete": True,
            "json_fragment": "",
        }
        return _page(result, text, offset, limit)

    def _check_revision(self, expected_revision: int) -> None:
        expected = _integer(expected_revision, "expected revision")
        if expected != self.revision:
            raise NotebookError(
                "stale_revision", "Notebook revision changed; read the current view."
            )

    def _accept(self, candidate: JsonValue) -> dict:
        canonical = encode(candidate)
        changed = canonical != self._bytes
        if changed:
            self._value, self._bytes = candidate, canonical
            self._revision += 1
        return {
            "status": "ok",
            "revision": self.revision,
            "byte_size": self.byte_size,
            "changed": changed,
        }

    def write(self, pointer: str, value_json: str, *, expected_revision: int) -> dict:
        """Set an object member/array slot, append at '-' or len, or replace the root."""
        self._check_revision(expected_revision)
        return self._accept(tree.change(self._value, pointer, "write", decode(value_json)))

    def delete(self, pointer: str, *, expected_revision: int) -> dict:
        """Remove an existing value; deleting the root clears this notebook to {}."""
        self._check_revision(expected_revision)
        return self._accept(tree.change(self._value, pointer, "remove"))

    def edit(self, operations: list[dict], *, expected_revision: int) -> dict:
        """Atomically apply JSON Patch add/replace/remove/test using raw value_json fields."""
        self._check_revision(expected_revision)
        if type(operations) is not list:
            raise NotebookError("invalid_argument", "Notebook edits must be a list of operations.")
        candidate = self._value
        for operation in operations:
            name, pointer, addition = _operation(operation)
            candidate = _apply(candidate, name, pointer, addition)
        return self._accept(candidate)


def _operation(operation: dict) -> tuple[str, str, JsonValue]:
    if type(operation) is not dict or set(operation) - {"op", "path", "value_json"}:
        raise NotebookError("invalid_argument", "Notebook edit has unsupported fields.")
    name, pointer = operation.get("op"), operation.get("path")
    if type(name) is not str or name not in {"add", "replace", "remove", "test"}:
        raise NotebookError("invalid_argument", "Notebook edit operation is unavailable.")
    if not isinstance(pointer, str):
        raise NotebookError("invalid_argument", "Notebook edit path must be a JSONPointer.")
    tree.tokens(pointer)
    needs_value = name != "remove"
    if needs_value != ("value_json" in operation):
        raise NotebookError("invalid_argument", "Only add/replace/test edits require value_json.")
    addition = decode(operation["value_json"]) if needs_value else None
    return name, pointer, addition


def _apply(value: JsonValue, name: str, pointer: str, addition: JsonValue) -> JsonValue:
    if name != "test":
        return tree.change(value, pointer, name, addition)
    if not tree.equal(tree.lookup(value, pointer), addition):
        raise NotebookError("test_failed", "Notebook edit test did not match the current value.")
    return value


def _page(result: dict, text: str, offset: int, limit: int) -> dict:
    left, right = 0, min(len(text) - offset, limit)
    while left < right:
        count = (left + right + 1) // 2
        _fragment(result, text, offset, count)
        if _size(result) <= limit:
            left = count
        else:
            right = count - 1
    _fragment(result, text, offset, left)
    if _size(result) > limit or (not result["complete"] and not left):
        raise NotebookError("read_budget_exhausted", "Notebook read metadata exceeds its budget.")
    return result


def _fragment(result: dict, text: str, offset: int, count: int) -> None:
    end = offset + count
    result.update(
        json_fragment=text[offset:end],
        complete=end == len(text),
        next_offset=end if end < len(text) else None,
    )
