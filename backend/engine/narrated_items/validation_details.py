"""Bounded field and constraint diagnostics without model inputs or provider messages."""

from pydantic import ValidationError
from pydantic_core import ErrorDetails

_FIELDS = {
    "actions",
    "condition_updates",
    "item_id",
    "new_item",
    "source_owner",
    "destination_owner",
    "disposition",
    "evidence",
    "basis",
    "name",
    "description",
    "kind",
    "clothing",
    "wearable_slots",
    "category",
    "layer",
    "coverage",
    "opaque",
    "underwear",
}
_NEW_ITEM_FIELDS = {"name", "description", "kind", "clothing", "wearable_slots"}
_REASONS = {
    "missing": "Required field is missing.",
    "none_required": "This field must be null for this item identity.",
    "literal_error": "Value is outside the permitted item choices.",
    "enum": "Value is outside the permitted item choices.",
    "union_tag_invalid": "Item kind must be ordinary or clothing.",
    "union_tag_not_found": "Item kind is required to select its metadata schema.",
    "extra_forbidden": "Unexpected field is not allowed.",
    "string_type": "A text value is required.",
    "list_type": "An array is required.",
    "model_type": "An item or garment object is required.",
    "int_type": "An integer is required.",
    "bool_type": "A boolean is required.",
}
_CUSTOM_REASONS = {
    "Clothing requires garment metadata and slots.",
    "Ordinary items cannot carry clothing metadata.",
    "Use an existing ID or a new item, never both.",
    "Coverage regions must be unique.",
}
_CODES = set(_REASONS) | {
    "too_short",
    "too_long",
    "string_too_short",
    "string_too_long",
    "value_error",
    "greater_than",
    "greater_than_equal",
    "less_than",
    "less_than_equal",
}


def details(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": _path(item["loc"]),
            "code": item["type"] if item["type"] in _CODES else "invalid_value",
            "reason": _reason(item),
        }
        for item in error.errors(include_input=False, include_url=False)[:5]
    ]


def _path(location: tuple) -> str:
    parts = list(location)
    # A discriminated union's branch label is not an additional object field.
    for index in range(len(parts) - 2):
        if (
            parts[index] == "new_item"
            and parts[index + 1] in {"ordinary", "clothing"}
            and parts[index + 2] in _NEW_ITEM_FIELDS
        ):
            parts[index + 1] = ""
    return ".".join(str(part) for part in parts if type(part) is int or part in _FIELDS)[:200]


def _reason(item: ErrorDetails) -> str:
    code, context = item["type"], item.get("ctx", {})
    lengths = {
        "too_short": ("min_length", "at least", "items"),
        "too_long": ("max_length", "at most", "items"),
        "string_too_short": ("min_length", "at least", "characters"),
        "string_too_long": ("max_length", "at most", "characters"),
    }
    if code in lengths:
        key, comparison, unit = lengths[code]
        limit = context.get(key)
        if type(limit) is int and 0 <= limit <= 100000:
            return f"Value must contain {comparison} {limit} {unit}."
    if code == "value_error" and str(context.get("error")) in _CUSTOM_REASONS:
        return str(context["error"])
    return _REASONS.get(code, "Value does not satisfy the item or garment schema.")
