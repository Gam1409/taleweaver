"""Classify tool completion metadata without retaining provider text or importing transport."""

from typing import Any

_NATIVE_FINISH_REASONS = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "length",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "COMPLETE": "stop",
    "eos_token": "stop",
    "eos": "stop",
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "compaction": "length",
}


def _canonical_reason(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value in {"stop", "tool_calls", "length", "max_tokens"}:
        return value
    raise ValueError("The tool response has an unsupported finish reason.")


def classify_tool_finish(choice: object) -> str | None:
    """Reject failed/unknown flags even when an adapter normalized them to stop."""
    if not isinstance(choice, dict):
        raise ValueError("The tool response requires one completion choice object.")
    reason = _canonical_reason(choice.get("finish_reason"))
    fields = choice.get("provider_specific_fields")
    if not isinstance(fields, dict) or fields.get("native_finish_reason") is None:
        return reason
    native = fields["native_finish_reason"]
    # Adapters can map errors to stop; only explicit completion aliases count.
    if not isinstance(native, str) or native not in _NATIVE_FINISH_REASONS:
        raise ValueError("The tool response has an unsupported finish reason.")
    return "length" if _NATIVE_FINISH_REASONS[native] == "length" else reason
