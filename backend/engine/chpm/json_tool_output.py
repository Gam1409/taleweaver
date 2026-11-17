"""Optional provider output constraints for the existing portable function envelope."""

import inspect
import json
from typing import Any

from pydantic import BaseModel, JsonValue

from backend.core.llm_structured_output import for_router

MAX_REQUESTS = 2
SUBMISSION = "submit_decision"


class PortableToolEnvelope(BaseModel):
    """The outer transport only; current tool and workflow owners validate arguments."""

    requests: list[dict]
    purpose: JsonValue = None


def _batch(names: list[str], *, minimum: int, maximum: int) -> dict:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "enum": names},
                "arguments": {"type": "object"},
            },
            "required": ["name", "arguments"],
        }
        if names
        else False,
    }


def schema(tools: list[dict]) -> dict:
    """Describe current names and isolated submission without copying argument schemas."""
    names = sorted({tool["function"]["name"] for tool in tools})
    nonfinal = [name for name in names if name != SUBMISSION]
    batches = (
        [_batch([SUBMISSION], minimum=1, maximum=1)]
        if SUBMISSION in names
        else [_batch(nonfinal, minimum=0, maximum=MAX_REQUESTS if nonfinal else 0)]
    )
    if SUBMISSION in names and nonfinal:
        batches.append(_batch(nonfinal, minimum=1, maximum=MAX_REQUESTS))
    return {
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


def selected(inner: Any, tools: list[dict], *, model: str | None = None) -> dict | None:
    method = inner.aexecute_simple_task
    parameter = inspect.signature(method).parameters.get("response_format")
    if parameter is None or parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
        return None
    return for_router(
        inner, PortableToolEnvelope, schema=schema(tools), model=model
    ).response_format


def size(response_format: dict | None) -> int:
    return (
        len(json.dumps(response_format, ensure_ascii=False, separators=(",", ":")))
        if response_format is not None
        else 0
    )
