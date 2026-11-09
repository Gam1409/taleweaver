"""Bounded validation reasons for the owner; never echo candidate values or unknown fields."""

from pydantic import ValidationError
from pydantic_core import ErrorDetails

_FIELDS = {
    "operation",
    "condition_id",
    "target_id",
    "kind",
    "part",
    "detail",
    "visibility",
    "evidence",
}
_REASONS = {
    "missing": "Required field is missing.",
    "extra_forbidden": "Unexpected field is not allowed.",
    "literal_error": "Value is outside the permitted condition choices.",
    "string_type": "A text value is required.",
    "model_type": "A condition proposal object is required.",
}
_RULES = {
    "Recording requires target, kind, part and detail, without an existing condition ID.",
    "An update references only its existing condition ID, not a new target or body part.",
    "A description change requires the new detail.",
}


def rejection(index: int, error: ValidationError) -> str:
    details = [
        f"{_field(item['loc'])}: {_reason(item)}"
        for item in error.errors(include_input=False, include_url=False)[:5]
    ]
    return f"Condition proposal {index + 1}: " + "; ".join(details)


def _field(location: tuple) -> str:
    return ".".join(part for part in location if part in _FIELDS) or "proposal"


def _reason(item: ErrorDetails) -> str:
    code, context = item["type"], item.get("ctx", {})
    if code in {"string_too_short", "string_too_long"}:
        key, comparison = (
            ("min_length", "at least") if code == "string_too_short" else ("max_length", "at most")
        )
        limit = context.get(key)
        if type(limit) is int and 0 <= limit <= 600:
            return f"Text must contain {comparison} {limit} characters."
    if code == "value_error" and str(context.get("error")) in _RULES:
        return str(context["error"])
    return _REASONS.get(code, "Value does not satisfy the physical condition schema.")
