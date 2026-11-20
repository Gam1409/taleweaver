"""Optional output constraints and syntax diagnostics for the portable function envelope."""

import inspect
import json
import logging
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, JsonValue

from backend.core.llm_schema_choices import SchemaChoiceError
from backend.core.llm_schema_compaction import safe_to_share
from backend.core.llm_schema_merge import SchemaProjectionError
from backend.core.llm_structured_output import for_router
from backend.engine.chpm import required_tools
from backend.engine.chpm.agent_limits import MAX_TOOL_ARGUMENT_CHARS
from backend.engine.chpm.notebook.codec import decode

MAX_REQUESTS = 2
SUBMISSION = "submit_decision"
logger = logging.getLogger(__name__)


def syntax_error_code(error: json.JSONDecodeError) -> str:
    """Recognize one complete terminal request inside an otherwise unclosed requests array."""
    if (
        len(error.doc) > MAX_TOOL_ARGUMENT_CHARS
        or error.msg != "Expecting ',' delimiter"
        or error.doc[error.pos :].rstrip(" \t\r\n") != "}"
    ):
        return "invalid_json"
    header, _, element = error.doc[: error.pos].partition("[")
    opening, key, colon = header.partition('"requests"')
    if opening.strip() != "{" or not key or colon.strip() != ":":
        return "invalid_json"
    try:
        # Inspect only the original, complete array element. No synthesized wrapper
        # or decoded arguments can enter the execution path from a syntax error.
        item = decode(element)
    except ValueError:
        return "invalid_json"
    if (
        isinstance(item, dict)
        and set(item) == {"name", "arguments"}
        and item["name"] == SUBMISSION
        and isinstance(item["arguments"], dict)
    ):
        return "unclosed_requests_array"
    return "invalid_json"


class PortableToolEnvelope(BaseModel):
    """The outer transport only; current tool and workflow owners validate arguments."""

    requests: list[dict]
    purpose: JsonValue = None


def _request(name: dict, arguments: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"name": name, "arguments": arguments},
        "required": ["name", "arguments"],
    }


def _items(names: list[str], parameters: dict[str, dict] | None) -> dict | bool:
    if not names:
        return False
    if parameters is None:
        return _request({"type": "string", "enum": names}, {"type": "object"})
    alternatives = [_request({"type": "string", "const": name}, parameters[name]) for name in names]
    return alternatives[0] if len(alternatives) == 1 else {"anyOf": alternatives}


def _batch(
    names: list[str], *, minimum: int, maximum: int, parameters: dict[str, dict] | None
) -> dict:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": _items(names, parameters),
    }


def _arguments(tools: list[dict]) -> tuple[dict[str, dict], dict]:
    # Reuse the port's schema-only relocation without its prompt annotation filter.
    from backend.engine.chpm.json_tool_port import _global_parameters

    parameters: dict[str, dict] = {}
    definitions: dict = {}
    for tool in tools:
        function = tool["function"]
        original = function.get("parameters")
        if not isinstance(original, dict) or not safe_to_share(original):
            raise SchemaProjectionError("Tool arguments require their original reference scope.")
        parameters[function["name"]] = _global_parameters(deepcopy(original), definitions)
    return parameters, definitions


def schema(tools: list[dict], *, arguments: bool = False, require_tools: bool = False) -> dict:
    """Describe names and isolated batches, optionally binding canonical argument schemas."""
    parameters, definitions = _arguments(tools) if arguments else (None, {})
    names = sorted(
        required_tools.names(tools)
        if require_tools
        else {tool["function"]["name"] for tool in tools}
    )
    nonfinal = [name for name in names if name != SUBMISSION]
    batches = (
        [_batch([SUBMISSION], minimum=1, maximum=1, parameters=parameters)]
        if SUBMISSION in names
        else [
            _batch(
                nonfinal,
                minimum=int(require_tools),
                maximum=MAX_REQUESTS if nonfinal else 0,
                parameters=parameters,
            )
        ]
    )
    if SUBMISSION in names and nonfinal:
        batches.append(_batch(nonfinal, minimum=1, maximum=MAX_REQUESTS, parameters=parameters))
    result = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "requests": batches[0] if len(batches) == 1 else {"anyOf": batches},
            # Some grammar converters read an untyped {} as object-only, rather than any JSON.
            "purpose": {
                "anyOf": [
                    {"type": kind}
                    for kind in ("null", "boolean", "number", "string", "array", "object")
                ]
            },
        },
        "required": ["requests"],
    }
    if definitions:
        result["$defs"] = definitions
    return result


def selected(
    inner: Any, tools: list[dict], *, model: str | None = None, require_tools: bool = False
) -> dict | None:
    method = inner.aexecute_simple_task
    parameter = inspect.signature(method).parameters.get("response_format")
    if parameter is None or parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
        return None
    envelope = for_router(
        inner, PortableToolEnvelope, schema=schema(tools, require_tools=require_tools), model=model
    )
    if envelope.mode != "json_schema":
        return envelope.response_format
    try:
        complete = for_router(
            inner,
            PortableToolEnvelope,
            schema=schema(tools, arguments=True, require_tools=require_tools),
            model=model,
        )
    except (SchemaProjectionError, SchemaChoiceError, RecursionError):
        logger.warning("Portable tool schema: arguments=envelope reason=reference_scope")
        return envelope.response_format
    if complete.mode != "json_schema":
        logger.warning("Portable tool schema: arguments=envelope reason=schema_projection")
        return envelope.response_format
    logger.debug("Portable tool schema: arguments=structural")
    return complete.response_format


def size(response_format: dict | None) -> int:
    return (
        len(json.dumps(response_format, ensure_ascii=False, separators=(",", ":")))
        if response_format is not None
        else 0
    )
