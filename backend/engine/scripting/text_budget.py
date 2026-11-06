"""Measure container representations before CPython materializes their text."""

from collections.abc import ItemsView, KeysView, ValuesView
from types import BuiltinFunctionType, FunctionType, MethodType
from typing import Any

from backend.engine.scripting.errors import ScriptSecurityError


def bounded(size: int, limit: int) -> int:
    if size > limit:
        raise ScriptSecurityError("Operation exceeds the safe sequence/text size limit.")
    return size


def text_size(
    value: Any, limit: int, *, representation: bool = False, ascii_only: bool = False
) -> int:
    if isinstance(value, str) and not representation:
        return bounded(len(value), limit)
    return _measure(value, limit, set(), 0, ascii_only)


def _quoted_size(value: str | bytes, limit: int, ascii_only: bool) -> int:
    raw = value.decode("latin1") if isinstance(value, bytes) else value
    quote = '"' if "'" in raw and '"' not in raw else "'"
    size = 3 if isinstance(value, bytes) else 2
    for char in raw:
        code = ord(char)
        if char in {quote, "\\", "\n", "\r", "\t"}:
            size += 2
        elif char.isprintable() and (not ascii_only and not isinstance(value, bytes) or code < 127):
            size += 1
        else:
            size += 4 if code <= 255 else 6 if code <= 65535 else 10
        bounded(size, limit)
    return size


def _measure(value: Any, limit: int, active: set[int], depth: int, ascii_only: bool) -> int:
    if depth > 64:
        raise ScriptSecurityError("Container nesting exceeds the safe text depth.")
    if isinstance(value, (str, bytes)):
        return _quoted_size(value, limit, ascii_only)
    if isinstance(value, int) and value.bit_length() > 4 * max(1, limit):
        raise ScriptSecurityError("Integer text exceeds the safe size limit.")
    if isinstance(value, (int, float, bool, type(None))):
        return bounded(len(repr(value)), limit)
    if isinstance(value, (list, tuple, dict, KeysView, ValuesView, ItemsView)):
        return _container_size(value, limit, active, depth, ascii_only)
    if (
        isinstance(value, (FunctionType, BuiltinFunctionType, MethodType, type))
        or type(value).__repr__ is object.__repr__
    ):
        text = repr(value)
        return (
            _quoted_size(text, limit + 2, ascii_only) - 2
            if ascii_only
            else bounded(len(text), limit)
        )
    raise ScriptSecurityError("This object's custom text conversion is not supported in scripts.")


def _container_size(value: Any, limit: int, active: set[int], depth: int, ascii_only: bool) -> int:
    key = id(value)
    if key in active:
        return bounded(5, limit)
    active.add(key)
    try:
        size = 2
        if isinstance(value, (KeysView, ValuesView, ItemsView)):
            size += len(type(value).__name__) + 2
        for index, element in enumerate(value):
            size += 2 if index else 0
            size += _measure(element, max(0, limit - size), active, depth + 1, ascii_only)
            if isinstance(value, dict):
                size += 2
                size += _measure(
                    value[element], max(0, limit - size), active, depth + 1, ascii_only
                )
            bounded(size, limit)
        if isinstance(value, tuple) and len(value) == 1:
            size += 1
        return bounded(size, limit)
    finally:
        active.remove(key)


def payload_size(value: Any, limit: int, active: set[int] | None = None) -> int:
    """Bound expansion when script values enter a facade or persisted changeset."""
    active = set() if active is None else active
    if not isinstance(value, (list, tuple, dict)):
        return text_size(value, limit)
    if id(value) in active or len(active) > 64:
        raise ScriptSecurityError("Cyclic or deeply nested values cannot enter a script API.")
    active.add(id(value))
    try:
        size = 2
        elements = value.items() if isinstance(value, dict) else enumerate(value)
        for key, element in elements:
            if isinstance(value, dict):
                size += text_size(key, max(0, limit - size), representation=True)
            size += 2 + payload_size(element, max(0, limit - size), active)
            bounded(size, limit)
        return bounded(size, limit)
    finally:
        active.remove(id(value))
