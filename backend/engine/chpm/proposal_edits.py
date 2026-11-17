"""Apply bounded JSON field edits to a rejected, still-uncommitted proposal."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field, JsonValue, ValidationError, model_validator

from backend.engine.chpm.schema import Contract

MAX_PATHS = 256
MAX_DEPTH = 3
MAX_EDITS = 8
MAX_PATH_LENGTH = 300
INSTRUCTIONS = (
    "\nFIELD EDIT REPAIR: This round returns only the Corrections schema object. "
    "Earlier proposal rules still govern the reconstructed proposal's content and evidence. "
    "Use each allowed path once; combine deeper changes in one full parent/array replacement. "
    "The host retains unedited fields and validates the complete result."
)


class Edit(Contract):
    op: Literal["replace", "remove"]
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    value: JsonValue = None

    @model_validator(mode="after")
    def explicit_value(self) -> "Edit":
        if self.op == "replace" and "value" not in self.model_fields_set:
            raise ValueError("replace requires value, including explicit null.")
        if self.op == "remove" and self.value is not None:
            raise ValueError("remove omits value or uses null; it cannot set a value.")
        return self


class Corrections(Contract):
    edits: list[Edit] = Field(min_length=1, max_length=MAX_EDITS)


def paths(candidate: dict, schema: type[BaseModel]) -> list[str]:
    roots = {"/" + _escape(key) for key in schema.model_json_schema().get("properties", {})}
    remaining = max(0, MAX_PATHS - len(roots))
    children = sorted((set(_paths(candidate)) | set(_missing_paths(candidate, schema))) - roots)[
        :remaining
    ]
    return sorted(roots | set(children))[:MAX_PATHS]


def pointer(location: tuple[str | int, ...]) -> str:
    return "/" + "/".join(_escape(str(part)) for part in location)


def _missing_fields(candidate: dict, schema: type[BaseModel]) -> list[tuple[str | int, ...]] | None:
    try:
        schema.model_validate(deepcopy(candidate))
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        if len(errors) > MAX_PATHS:
            return None
        return [item["loc"] for item in errors if item["type"] == "missing"]
    return []


def _parent(candidate: dict, location: tuple[str | int, ...]) -> dict | None:
    parent: JsonValue = candidate
    try:
        for part in location[:-1]:
            parent = _member(parent, str(part))
    except ValueError:
        return None
    return parent if isinstance(parent, dict) else None


def _missing_paths(candidate: dict, schema: type[BaseModel]) -> list[str]:
    locations = _missing_fields(candidate, schema)
    if locations is None:
        return []
    result = []
    for location in locations:
        if not 1 < len(location) <= MAX_DEPTH or not isinstance(location[-1], str):
            continue
        path = pointer(location)
        if len(path) > MAX_PATH_LENGTH or _parent(candidate, location) is None:
            continue
        probe = deepcopy(candidate)
        parent = _parent(probe, location)
        if parent is None or location[-1] in parent:
            continue
        # A union branch label can coincide with an input key. Confirm that the
        # actual required field, rather than a diagnostic-only branch, is addressed.
        parent[location[-1]] = None
        remaining = _missing_fields(probe, schema)
        if remaining is not None and location not in remaining:
            result.append(path)
    return result


def _paths(value: JsonValue, prefix: str = "", depth: int = 0) -> list[str]:
    if depth >= MAX_DEPTH:
        return []
    items = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else ()
    )
    result = []
    for key, child in items:
        path = prefix + "/" + _escape(str(key))
        if len(path) > MAX_PATH_LENGTH:
            continue
        result.append(path)
        result.extend(_paths(child, path, depth + 1))
        if len(result) >= MAX_PATHS:
            return result[:MAX_PATHS]
    return result


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def apply(candidate: dict, edits: Corrections, schema: type[BaseModel]) -> dict:
    allowed = set(paths(candidate, schema))
    selected = [edit.path for edit in edits.edits]
    if len(set(selected)) != len(selected):
        raise ValueError("Proposal edits repeat a path.")
    if any(path not in allowed for path in selected):
        raise ValueError("Proposal edit refers to an unavailable path.")
    if any(a.startswith(b + "/") for a in selected for b in selected if a != b):
        raise ValueError("Proposal edits cannot overlap parent and child paths.")
    result = deepcopy(candidate)
    for edit in edits.edits:
        _apply(result, edit)
    return result


def _apply(candidate: dict, edit: Edit) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in edit.path[1:].split("/")]
    parent: JsonValue = candidate
    for part in parts[:-1]:
        parent = _member(parent, part)
    key = parts[-1]
    if isinstance(parent, dict):
        if edit.op == "replace":
            parent[key] = deepcopy(edit.value)
            return
        _remove(parent, key)
        return
    if isinstance(parent, list) and edit.op == "replace":
        parent[_index(parent, key)] = deepcopy(edit.value)
        return
    raise ValueError("Replace an entire array to remove elements; scalar parents cannot be edited.")


def _remove(parent: dict, key: str) -> None:
    if key not in parent:
        raise ValueError("Proposal edit cannot remove a missing field.")
    del parent[key]


def _member(parent: JsonValue, key: str) -> JsonValue:
    if isinstance(parent, dict) and key in parent:
        return parent[key]
    if isinstance(parent, list):
        return parent[_index(parent, key)]
    raise ValueError("Proposal edit refers to a missing or scalar parent.")


def _index(parent: list, key: str) -> int:
    if not key.isascii() or not key.isdecimal() or (len(key) > 1 and key.startswith("0")):
        raise ValueError("Proposal array edits need an existing zero-based index.")
    index = int(key)
    if index >= len(parent):
        raise ValueError("Proposal array edit index is unavailable.")
    return index
