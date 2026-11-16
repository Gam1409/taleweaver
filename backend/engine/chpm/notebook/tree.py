"""JSON Pointer traversal and path-only copy-on-write document changes."""

import re

from backend.engine.chpm.notebook.codec import JsonValue, NotebookError


def tokens(pointer: str) -> tuple[str, ...]:
    """Decode RFC 6901 escapes; paths never refer to files or Python attributes."""
    if type(pointer) is not str or (pointer and not pointer.startswith("/")):
        raise NotebookError("invalid_pointer", "Notebook paths must be JSON Pointers.")
    if re.search(r"~(?![01])", pointer):
        raise NotebookError("invalid_pointer", "Notebook pointer has an invalid escape.")
    if not pointer:
        return ()
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def _index(component: str, length: int, *, allow_end: bool = False) -> int:
    if component == "-" and allow_end:
        return length
    if not re.fullmatch(r"0|[1-9][0-9]*", component) or len(component) > len(str(length)):
        raise NotebookError("invalid_index", "Notebook array indices must be canonical integers.")
    index = int(component)
    if index >= length + int(allow_end):
        raise NotebookError("missing_path", "Notebook array index is unavailable.")
    return index


def _child(value: JsonValue, token: str) -> JsonValue:
    if isinstance(value, list):
        return value[_index(token, len(value))]
    if not isinstance(value, dict):
        raise NotebookError("missing_path", "Notebook path does not identify a container.")
    if token not in value:
        raise NotebookError("missing_path", "Notebook path is unavailable.")
    return value[token]


def lookup(value: JsonValue, pointer: str) -> JsonValue:
    for token in tokens(pointer):
        value = _child(value, token)
    return value


def _object_change(value: dict, token: str, operation: str, addition: JsonValue) -> dict:
    if operation in {"replace", "remove"} and token not in value:
        raise NotebookError("missing_path", "Notebook path is unavailable.")
    result = dict(value)
    if operation == "remove":
        del result[token]
    else:
        result[token] = addition
    return result


def _array_change(value: list, token: str, operation: str, addition: JsonValue) -> list:
    index = _index(token, len(value), allow_end=operation in {"add", "write"})
    result = list(value)
    if operation == "remove":
        result.pop(index)
    elif operation == "add":
        result.insert(index, addition)
    elif index == len(result):
        result.append(addition)
    else:
        result[index] = addition
    return result


def _change_parent(value: JsonValue, token: str, operation: str, addition: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return _object_change(value, token, operation, addition)
    if isinstance(value, list):
        return _array_change(value, token, operation, addition)
    raise NotebookError("missing_path", "Notebook path does not identify a container.")


def change(value: JsonValue, pointer: str, operation: str, addition: JsonValue = None) -> JsonValue:
    """Copy affected containers only; removing the document root resets it to {}."""
    parts = tokens(pointer)
    if not parts:
        return {} if operation == "remove" else addition
    ancestors = []
    parent = value
    for token in parts[:-1]:
        ancestors.append((parent, token))
        parent = _child(parent, token)
    changed = _change_parent(parent, parts[-1], operation, addition)
    for container, token in reversed(ancestors):
        changed = _change_parent(container, token, "replace", changed)
    return changed


def equal(left: JsonValue, right: JsonValue) -> bool:
    """JSON numbers compare numerically; booleans never compare equal to numbers."""
    pending = [(left, right)]
    while pending:
        one, two = pending.pop()
        if type(one) in {int, float} and type(two) in {int, float}:
            if one != two:
                return False
            continue
        if type(one) is not type(two):
            return False
        if isinstance(one, dict) and isinstance(two, dict):
            if one.keys() != two.keys():
                return False
            pending.extend((value, two[key]) for key, value in one.items())
        elif isinstance(one, list) and isinstance(two, list):
            if len(one) != len(two):
                return False
            pending.extend(zip(one, two, strict=True))
        elif one != two:
            return False
    return True
