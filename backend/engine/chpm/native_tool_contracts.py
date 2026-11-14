"""Native memory tools with strict argument decoding and unrestricted JSON values."""

import json
import math
from copy import deepcopy
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.notebook.codec import MAX_BYTES, NotebookError, encode, preflight
from backend.engine.chpm.notebook.tree import tokens
from backend.engine.chpm.notebook_requests import (
    NotebookDelete,
    NotebookEdit,
    NotebookInfo,
    NotebookRead,
    NotebookRequest,
    NotebookWrite,
)

MAX_VALUE_CHARS = 8192
MAX_OPERATIONS = 16
MAX_ERROR_CHARS = 400
_LOOKUPS = {
    "search_memory": "Search this observer's source-checked prior turns. A miss proves nothing.",
    "read_memory": "Read an ID returned by search_memory in this turn.",
    "inspect_self": "Inspect current host facts about this NPC's own location and possessions.",
    "visible_clothing": "Read visible clothing of an accessible actor ID, using argument.",
    "inspect_beliefs": "Inspect this NPC's own subjective beliefs about the subject in argument.",
    "read_belief_basis": "Read grounds for an ID returned by inspect_beliefs.",
}
_NOTEBOOKS: dict[str, type[BaseModel]] = {
    "notebook_info": NotebookInfo,
    "notebook_read": NotebookRead,
    "notebook_write": NotebookWrite,
    "notebook_edit": NotebookEdit,
    "notebook_delete": NotebookDelete,
}
_DESCRIPTIONS = {
    "notebook_info": "Read this private notebook's current modification counter and byte quota.",
    "notebook_read": "Read a bounded page of your private JSON notebook. Root path is the empty string, not '/'.",
    "notebook_write": "Privately set a JSON value at a JSON Pointer, or replace the root. Notes are subjective data, not world evidence or spoken disclosure.",
    "notebook_edit": "Atomically add, replace, remove or test JSON values in your private notebook. All operations must be valid before any change is accepted.",
    "notebook_delete": "Remove a value from this private notebook. Deleting root path '' resets this one document to {}.",
}
_POINTER = "RFC 6901 JSON Pointer. '' selects the root; '/' selects an empty-name member. Escape '/' as '~1' and '~' as '~0'."
_VALUE = {
    "description": "Any strict JSON value: null, boolean, number, string, array or object with freely chosen keys. No fixed notebook layout. Each value's canonical JSON must fit 8192 characters."
}
_KNOWN_TOOL_NAMES = frozenset((*_LOOKUPS, *_NOTEBOOKS))


def known_tool_names() -> frozenset[str]:
    """Return the immutable capability allowlist without private model-supplied text."""
    return _KNOWN_TOOL_NAMES


def canonical_tool_name(name: object) -> str:
    """Keep only declared names in audit and feedback metadata."""
    return name if type(name) is str and name in _KNOWN_TOOL_NAMES else "unknown_tool"


class NativeToolArgumentError(ValueError):
    """Bounded feedback that never includes raw private arguments or values."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message[:MAX_ERROR_CHARS]
        super().__init__(self.message)


def _parameters(name: str) -> dict:
    model = Lookup if name in _LOOKUPS else _NOTEBOOKS[name]
    parameters = model.model_json_schema()
    parameters.pop("title", None)
    parameters["properties"].pop("tool")
    parameters["required"] = [field for field in parameters.get("required", []) if field != "tool"]
    if name in _LOOKUPS:
        return _lookup_parameters(name, parameters)
    if "path" in parameters["properties"]:
        parameters["properties"]["path"]["description"] = _POINTER
    if name == "notebook_write":
        parameters["properties"].pop("value_json")
        parameters["properties"]["value"] = deepcopy(_VALUE)
        parameters["required"] = [
            "value" if field == "value_json" else field for field in parameters["required"]
        ]
    if name == "notebook_edit":
        parameters["properties"]["operations"]["items"] = _operation_schema(
            parameters["$defs"]["NotebookOperation"]
        )
        parameters.pop("$defs")
    return parameters


def _lookup_parameters(name: str, parameters: dict) -> dict:
    if name == "inspect_self":
        parameters.update(properties={}, required=[])
        return parameters
    parameters["properties"]["argument"]["minLength"] = 1
    parameters["required"] = ["argument"]
    return parameters


def _operation_schema(original: dict) -> dict:
    path = {**original["properties"]["path"], "description": _POINTER}
    valued = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "op": {"type": "string", "enum": ["add", "replace", "test"]},
            "path": path,
            "value": deepcopy(_VALUE),
        },
        "required": ["op", "path", "value"],
    }
    removed = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"op": {"type": "string", "const": "remove"}, "path": path},
        "required": ["op", "path"],
    }
    return {"anyOf": [valued, removed]}


def tool_definitions(notebook_enabled: bool = True) -> list[dict]:
    """Return distinct native functions; only argument envelopes have closed schemas."""
    names = [*_LOOKUPS, *(_NOTEBOOKS if notebook_enabled else {})]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": _LOOKUPS.get(name, _DESCRIPTIONS.get(name, "")),
                "parameters": _parameters(name),
                "strict": False,
            },
        }
        for name in names
    ]


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeToolArgumentError(
                "invalid_json",
                "Tool arguments contain a duplicate JSON key. Send each key only once.",
            )
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise NativeToolArgumentError("invalid_json", "Tool arguments must use finite JSON numbers.")


def _check_scalars(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            item.encode("utf-8")
        elif type(item) is float and not math.isfinite(item):
            _constant("")
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def _arguments(raw: str) -> dict:
    if type(raw) is not str:
        raise NativeToolArgumentError(
            "invalid_json", "Tool arguments must be a raw JSON object string."
        )
    try:
        text = preflight(raw, extra_depth=4, extra_nodes=256, max_transport_bytes=MAX_BYTES + 4096)
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _check_scalars(value)
    except NativeToolArgumentError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise NativeToolArgumentError(
            "invalid_json",
            "Tool arguments must be complete, finite UTF-8 JSON within the resource limits.",
        ) from None
    if type(value) is not dict:
        raise NativeToolArgumentError(
            "invalid_arguments", "Tool arguments must be one JSON object."
        )
    return value


def _fields(value: dict, allowed: set[str]) -> None:
    if set(value) - allowed:
        raise NativeToolArgumentError(
            "invalid_arguments",
            "Unexpected argument fields. Use only this function's declared arguments; notebook scope is host-owned.",
        )


def _value_json(value: Any) -> str:
    try:
        canonical = encode(value).decode("utf-8")
    except NotebookError as exc:
        raise NativeToolArgumentError(
            exc.code, "The JSON value exceeds the notebook's JSON structure or size limits."
        ) from None
    if len(canonical) > MAX_VALUE_CHARS:
        raise NativeToolArgumentError(
            "value_limit",
            "Each value must encode to at most 8192 JSON characters. Write smaller subtrees.",
        )
    return canonical


def _operation(value: Any) -> dict:
    if type(value) is not dict:
        raise NativeToolArgumentError(
            "invalid_arguments",
            "Each edit operation must be an object with op, path, and value where required.",
        )
    _fields(value, {"op", "path", "value"})
    name = value.get("op")
    if type(name) is not str or name not in {"add", "replace", "remove", "test"}:
        raise NativeToolArgumentError(
            "invalid_arguments", "Edit op must be add, replace, remove, or test."
        )
    if (name == "remove") == ("value" in value):
        raise NativeToolArgumentError(
            "invalid_arguments",
            "Add, replace, and test require value, including explicit null; remove must omit value.",
        )
    result = dict(value)
    if "value" in result:
        result["value_json"] = _value_json(result.pop("value"))
    return result


def _prepare(name: str, arguments: dict) -> dict:
    _fields(arguments, set(_parameters(name)["properties"]))
    result = dict(arguments)
    if name == "notebook_write":
        if "value" not in result:
            raise NativeToolArgumentError(
                "invalid_arguments", "notebook_write requires value, including explicit null."
            )
        result["value_json"] = _value_json(result.pop("value"))
    if name == "notebook_edit":
        operations = result.get("operations")
        if type(operations) is not list or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise NativeToolArgumentError(
                "invalid_arguments", "notebook_edit requires 1 to 16 operations."
            )
        result["operations"] = [_operation(operation) for operation in operations]
    return result


def _validation_message(error: ValidationError) -> str:
    known = {
        "argument",
        "path",
        "expected_revision",
        "offset",
        "limit",
        "operations",
        "op",
        "value_json",
    }
    entry = error.errors(include_input=False, include_url=False)[0]
    fields = ["value" if key == "value_json" else key for key in entry["loc"] if key in known]
    field = ".".join(fields) or "arguments"
    return f"Invalid {field}: {entry['type']}. Follow the declared field types, required fields, and bounds."


def _validate_paths(request: Lookup | NotebookRequest) -> None:
    try:
        if isinstance(request, (NotebookRead, NotebookWrite, NotebookDelete)):
            tokens(request.path)
        if isinstance(request, NotebookEdit):
            for operation in request.operations:
                tokens(operation.path)
    except NotebookError:
        raise NativeToolArgumentError(
            "invalid_pointer",
            "Use a valid JSON Pointer: root is '', '/' is an empty-name member, '~1' escapes '/' and '~0' escapes '~'.",
        ) from None


def parse_call(name: str, arguments_raw: str) -> Lookup | NotebookRequest:
    """Strictly decode one pure request; callers validate the full batch before execution."""
    if type(name) is not str or name not in _KNOWN_TOOL_NAMES:
        raise NativeToolArgumentError(
            "invalid_tool", "Unknown tool. Use one of the declared native function names."
        )
    prepared = _prepare(name, _arguments(arguments_raw))
    model = Lookup if name in _LOOKUPS else _NOTEBOOKS[name]
    try:
        request = cast(Lookup | NotebookRequest, model.model_validate({"tool": name, **prepared}))
    except ValidationError as exc:
        raise NativeToolArgumentError("invalid_arguments", _validation_message(exc)) from None
    _validate_paths(request)
    return request
