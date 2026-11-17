"""Native memory tools with strict argument decoding and unrestricted JSON values."""

import json
import math
from copy import deepcopy
from typing import Any, NoReturn, cast

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
_Issue = tuple[str, str, str]
_HINTS = {
    "argument": "nonempty string, at most 160 characters",
    "path": "JSON Pointer string <=8192; '' only for intentional root",
    "expected_revision": "nonnegative integer; current revision, not a string/bool",
    "offset": "integer >=0",
    "limit": "integer 256..1400",
    "operations": "1 to 16 operation objects",
    "op": "add, replace, remove, or test",
    "value": "JSON value required; null is allowed",
}
_LOOKUPS = {
    "search_memory": "Search this observer's source-checked prior turns. A miss proves nothing.",
    "read_memory": "Read an ID returned by search_memory in this turn.",
    "inspect_self": "Inspect current host facts about this NPC's own location and possessions.",
    "inspect_entity": "Read current recorded conditions, ownership and wear/placement of an accessible exact entity ID. Omitted facts are unknown; this never performs an action.",
    "find_entity": "Find accessible actors/items by name or ID, including omitted index entries. Returns exact IDs; a miss proves nothing.",
    "inspect_scene": "Read the current room's public facts, actors and known routes. No arguments or movement.",
    "visible_clothing": "Read a listed visible_clothing_actors NPC's clothing. For the player use inspect_entity(argument='@player').",
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
    if name in {"notebook_write", "notebook_delete"}:
        parameters["properties"]["path"].pop("default", None)
        parameters["required"].append("path")
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
    if name in {"inspect_self", "inspect_scene"}:
        parameters.update(properties={}, required=[])
        return parameters
    parameters["properties"]["argument"]["minLength"] = 1
    descriptions = {
        "find_entity": "Name fragment or existing ID. Use returned IDs unchanged.",
        "inspect_entity": "Exact observable_entities/find_entity ID, observer_id for yourself, or @player. Never invent IDs.",
        "visible_clothing": "NPC ID from visible_clothing_actors; never @player.",
    }
    if name in descriptions:
        parameters["properties"]["argument"]["description"] = descriptions[name]
    parameters["properties"]["argument"].pop("title", None)
    parameters["properties"]["argument"].pop("default", None)
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


def tool_definitions(
    notebook_enabled: bool = True, *, available_lookups: set[str] | None = None
) -> list[dict]:
    """Return distinct native functions; only argument envelopes have closed schemas."""
    names = [
        *(name for name in _LOOKUPS if available_lookups is None or name in available_lookups),
        *(_NOTEBOOKS if notebook_enabled else {}),
    ]
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


def _known_fields(value: dict, allowed: set[str], issues: list[_Issue], field: str) -> dict:
    if set(value) - allowed:
        issues.append(
            (
                field,
                "invalid_arguments",
                "unexpected fields; declared arguments only; scope is host-owned",
            )
        )
    return {key: item for key, item in value.items() if key in allowed}


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


def _converted(value: Any, issues: list[_Issue], field: str) -> str:
    try:
        return _value_json(value)
    except NativeToolArgumentError as exc:
        issues.append((field, exc.code, exc.message))
        return "null"  # Validation probe only; the recorded issue prevents returning a request.


def _pointer(value: Any, issues: list[_Issue], field: str) -> None:
    if type(value) is not str or len(value) > 8192:
        return
    try:
        tokens(value)
    except NotebookError:
        issues.append(
            (field, "invalid_pointer", "JSON Pointer; ''=root, '/'=empty key; escape ~0/~1")
        )


def _operation(value: Any, index: int, issues: list[_Issue]) -> Any:
    if type(value) is not dict:
        return value
    field = f"operations[{index}]"
    result = _known_fields(value, {"op", "path", "value"}, issues, field)
    name = result.get("op")
    _pointer(result.get("path"), issues, f"{field}.path")
    if name == "remove" and "value" in result:
        issues.append((f"{field}.value", "invalid_arguments", "remove must omit value"))
        result.pop("value")
    if type(name) is str and name in {"add", "replace", "test"} and "value" not in result:
        issues.append((f"{field}.value", "invalid_arguments", _HINTS["value"]))
        result["value_json"] = "null"  # Keep collecting other fields; this request is rejected.
    if "value" in result:
        result["value_json"] = _converted(result.pop("value"), issues, f"{field}.value")
    return result


def _prepare(name: str, arguments: dict, issues: list[_Issue]) -> dict:
    parameters = _parameters(name)
    result = _known_fields(arguments, set(parameters["properties"]), issues, "arguments")
    issues.extend(
        (field, "invalid_arguments", _HINTS[field])
        for field in parameters["required"]
        if field not in result
    )
    _pointer(result.get("path"), issues, "path")
    if name == "notebook_write" and "value" in result:
        result["value_json"] = _converted(result.pop("value"), issues, "value")
    if name == "notebook_edit":
        operations = result.get("operations")
        if type(operations) is not list or not 1 <= len(operations) <= MAX_OPERATIONS:
            issues.append(("operations", "invalid_arguments", _HINTS["operations"]))
            result.pop("operations", None)
        else:
            result["operations"] = [
                _operation(operation, index, issues) for index, operation in enumerate(operations)
            ]
    return result


def _field(location: tuple, default: str) -> str:
    result = ""
    for key in location:
        if type(key) is int and 0 <= key < MAX_OPERATIONS and result:
            result += f"[{key}]"
        elif type(key) is str and key in {*_HINTS, "value_json"}:
            result += ("." if result else "") + ("value" if key == "value_json" else key)
    return result or default


def _validation_issues(error: ValidationError, name: str) -> list[_Issue]:
    result = []
    for entry in error.errors(include_input=False, include_url=False, include_context=False):
        field = _field(entry["loc"], "argument" if name in _LOOKUPS else "arguments")
        leaf = field.rsplit(".", 1)[-1]
        hint = _HINTS.get(leaf, "operation object with op, path and value")
        result.append((field, "invalid_arguments", hint))
    return result


def _issue_order(item: tuple[str, tuple[str, str]]) -> tuple[int, str]:
    field = item[0]
    index = field.partition("[")[2].partition("]")[0]
    return (int(index) if index else -1), field


def _reject(issues: list[_Issue]) -> NoReturn:
    unique: dict[str, tuple[str, str]] = {}
    for field, code, hint in issues:
        unique.setdefault(field, (code, hint))
    rendered: list[str] = []
    for field, (_, hint) in sorted(unique.items(), key=_issue_order)[:6]:
        candidate = "; ".join([*rendered, f"{field}: {hint}"])
        remaining = len(unique) - len(rendered) - 1
        suffix = f"; +{remaining} more issues" if remaining else ""
        if len(candidate + suffix) > MAX_ERROR_CHARS:
            break
        rendered.append(f"{field}: {hint}")
    remaining = len(unique) - len(rendered)
    message = "; ".join(rendered) + (f"; +{remaining} more issues" if remaining else "")
    code = next(iter(unique.values()))[0] if len(unique) == 1 else "invalid_arguments"
    raise NativeToolArgumentError(code, message) from None


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
            "invalid_tool", "Unknown tool. Allowed: " + ", ".join([*_LOOKUPS, *_NOTEBOOKS])
        )
    issues: list[_Issue] = []
    prepared = _prepare(name, _arguments(arguments_raw), issues)
    model = Lookup if name in _LOOKUPS else _NOTEBOOKS[name]
    try:
        request = cast(Lookup | NotebookRequest, model.model_validate({"tool": name, **prepared}))
    except ValidationError as exc:
        issues.extend(_validation_issues(exc, name))
        _reject(issues)
    if issues:
        _reject(issues)
    _validate_paths(request)
    return request
