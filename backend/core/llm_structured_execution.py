"""Completion checks for explicitly bounded structured requests."""

import json
from typing import Any

from backend.core.llm_completion_capture import Completion
from backend.core.llm_output_errors import StructuredOutputError


def require_input_budget(kwargs: dict[str, Any], max_input_chars: int | None) -> None:
    """Measure the prepared model input, including its response/function contracts."""
    if max_input_chars is None:
        return
    if type(max_input_chars) is not int or max_input_chars <= 0:
        raise ValueError("max_input_chars must be a positive integer.")
    fields = {
        key: kwargs[key]
        for key in ("messages", "tools", "tool_choice", "response_format")
        if key in kwargs
    }
    measured = len(json.dumps(fields, ensure_ascii=False))
    if measured > max_input_chars:
        raise ValueError(
            f"Prepared LLM input exceeds its character limit ({measured} > {max_input_chars}). "
            "No request was sent."
        )


def require_complete(records: list[Completion]) -> None:
    """Reuse the captured canonical/native finish classification before typed parsing."""
    if len(records) != 1 or records[0].tool_rejected:
        raise StructuredOutputError(
            "LLM structured response has unsupported completion metadata. No retry was sent."
        )
    reason = records[0].tool_finish_reason
    if reason in {"length", "max_tokens"}:
        raise StructuredOutputError(
            "LLM structured response was truncated (token limit). No retry was sent."
        )
    if reason != "stop":
        raise StructuredOutputError(
            "LLM structured response did not finish with a complete stop. No retry was sent."
        )
