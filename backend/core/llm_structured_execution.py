"""Completion checks for explicitly bounded structured requests."""

import json
from typing import Any

from backend.core.llm_completion_capture import Completion
from backend.core.llm_output_errors import StructuredOutputError


class InputBudgetError(ValueError):
    """A prepared request was rejected locally before provider dispatch."""

    def __init__(self, measured: int, limit: int):
        self.measured = measured
        self.limit = limit
        super().__init__(
            f"Prepared LLM input exceeds its character limit ({measured} > {limit}). "
            "No request was sent."
        )


class OutputLimitError(StructuredOutputError):
    """The provider completed transport but ran out of generation budget."""


def input_characters(kwargs: dict[str, Any]) -> int:
    fields = {
        key: kwargs[key]
        for key in ("messages", "tools", "tool_choice", "response_format")
        if key in kwargs
    }
    return len(json.dumps(fields, ensure_ascii=False))


def require_input_budget(kwargs: dict[str, Any], max_input_chars: int | None) -> None:
    """Measure the prepared model input, including its response/function contracts."""
    if max_input_chars is None:
        return
    if type(max_input_chars) is not int or max_input_chars <= 0:
        raise ValueError("max_input_chars must be a positive integer.")
    measured = input_characters(kwargs)
    if measured > max_input_chars:
        raise InputBudgetError(measured, max_input_chars)


def require_complete(records: list[Completion], *, task: str = "structured") -> None:
    """Reuse the captured canonical/native finish classification before typed parsing."""
    if len(records) != 1 or records[0].tool_rejected:
        raise StructuredOutputError(
            f"LLM {task} response has unsupported completion metadata. No retry was sent."
        )
    reason = records[0].tool_finish_reason
    if reason in {"length", "max_tokens"}:
        raise OutputLimitError(
            f"LLM {task} response was truncated (token limit). No retry was sent."
        )
    if reason != "stop":
        raise StructuredOutputError(
            f"LLM {task} response did not finish with a complete stop. No retry was sent."
        )
