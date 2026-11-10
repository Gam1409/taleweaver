"""Shared output policy for technical calls through the existing provider router."""

import hashlib
import json
import logging
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from backend.core.llm_provider_config import (
    is_minimax_model,
    normalize_model,
    uses_json_mode_fallback,
)
from backend.core.llm_schema_merge import SchemaProjectionError
from backend.core.llm_schema_projection import project

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutputContract:
    response_format: dict | None
    mode: str
    local_checks: tuple[str, ...] = ()


def trace(response_format: dict | None, *, local_checks: tuple[str, ...] | None = None) -> None:
    """Record the requested contract, never its text or a claim of remote enforcement."""
    from backend.core.llm_diagnostics import emit

    selected = response_format or {}
    mode = selected.get("type", "prompt")
    fields: dict[str, Any] = {"output_mode": mode}
    wrapper = selected.get("json_schema")
    schema = wrapper.get("schema") if isinstance(wrapper, dict) else None
    if isinstance(schema, dict):
        encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
        fields["schema_fingerprint"] = hashlib.sha256(encoded).hexdigest()
    if local_checks is not None:
        fields["local_check_count"] = len(local_checks)
    emit("llm.output_contract", **fields)


def for_router(
    router: Any,
    response_model: type[BaseModel],
    *,
    schema: dict | None = None,
    model: str | None = None,
) -> OutputContract:
    provider = getattr(router, "provider", "")
    if not isinstance(provider, str) or not provider:
        return OutputContract(None, "prompt")
    normalized = normalize_model(provider, model or getattr(router, "model", "") or "")
    return select(
        provider,
        normalized,
        response_model,
        schema=schema,
        custom_mode=getattr(router, "custom_response_format", "prompt"),
    )


def select(
    provider: str,
    model: str,
    response_model: type[BaseModel],
    *,
    schema: dict | None = None,
    custom_mode: str = "prompt",
) -> OutputContract:
    mode = _mode(provider, model, custom_mode)
    if mode != "json_schema":
        return _simple(mode)
    try:
        projected = project(schema if schema is not None else response_model.model_json_schema())
        contract = _native_schema(projected.schema, provider)
    except SchemaProjectionError:
        fallback = "prompt" if provider == "anthropic" else "json_object"
        logger.debug(
            "Structured output fallback: provider=%s mode=%s reason=schema_projection",
            provider,
            fallback,
        )
        return OutputContract(_simple(fallback).response_format, fallback, ("schema_projection",))
    wrapper: dict[str, Any] = {"name": response_model.__name__, "schema": contract}
    if provider == "openai":
        wrapper["strict"] = True
    logger.debug(
        "Structured output: provider=%s mode=json_schema local_checks=%s",
        provider,
        projected.local_checks,
    )
    return OutputContract(
        {"type": "json_schema", "json_schema": wrapper}, mode, projected.local_checks
    )


def _mode(provider: str, model: str, custom_mode: str) -> str:
    if provider == "custom_openai":
        return custom_mode
    if not provider or is_minimax_model(provider, model):
        return "prompt"
    if provider == "anthropic":
        return "json_schema"
    return "json_object" if uses_json_mode_fallback(provider, model) else "json_schema"


def _simple(mode: str) -> OutputContract:
    if mode == "json_object":
        return OutputContract({"type": "json_object"}, mode)
    return OutputContract(None, "prompt")


def _strict(schema: dict) -> dict:
    """OpenAI strict objects must be closed and cannot have a root union."""
    result = deepcopy(schema)
    if result.get("type") != "object" or "anyOf" in result:
        raise SchemaProjectionError("Strict output requires a root object.")
    _strict_node(result)
    return result


def _native_schema(schema: dict, provider: str) -> dict:
    if provider == "openai":
        return _strict(schema)
    if provider == "anthropic":
        return _anthropic(schema)
    return schema


def _anthropic(schema: dict) -> dict:
    """Avoid a schema-less JSON mode: Anthropic needs a native schema or a tool."""
    result = deepcopy(schema)
    objects = list(_schema_nodes(result))
    if any(
        node.get("type") == "object" and node.get("additionalProperties") is not False
        for node in objects
    ):
        raise SchemaProjectionError("Anthropic output requires closed objects.")
    optional = sum(
        len(set(node.get("properties", {})) - set(node.get("required", []))) for node in objects
    )
    unions = sum("anyOf" in node for node in objects)
    if optional > 24 or unions > 16:
        raise SchemaProjectionError("Anthropic output exceeds its optional/union parameter limits.")
    return result


def _schema_nodes(node: Any) -> Iterator[dict]:
    if not isinstance(node, dict):
        return
    yield node
    for key in ("properties", "$defs"):
        for child in node.get(key, {}).values():
            yield from _schema_nodes(child)
    for key in ("items", "additionalProperties"):
        yield from _schema_nodes(node.get(key))
    for child in node.get("anyOf", []):
        yield from _schema_nodes(child)


def _strict_node(node: Any) -> None:
    if not isinstance(node, dict):
        return
    if any(key in node for key in ("minProperties", "maxProperties", "uniqueItems")):
        raise SchemaProjectionError("The strict schema requires local collection checks.")
    if node.get("type") == "object":
        if node.get("additionalProperties") is not False:
            raise SchemaProjectionError("Strict output cannot use an open dictionary.")
        node["required"] = list(node.get("properties", {}))
    for key in ("properties", "$defs"):
        for child in node.get(key, {}).values():
            _strict_node(child)
    for key in ("items", "additionalProperties"):
        _strict_node(node.get(key))
    for child in node.get("anyOf", []):
        _strict_node(child)
