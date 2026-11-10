"""Resolve current-message passage references before the existing strict validators."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from backend.core.text_passages import index


def passages(narration: str) -> dict[str, str]:
    return {"passage:" + key: text for key, text in index(narration).items()}


def bind(result: Any, narration: str) -> Any:
    """References select original text; unknown IDs and nonliteral quotes stay invalid."""
    available = passages(narration)
    body = result.model_dump() if isinstance(result, BaseModel) else deepcopy(result)
    if not isinstance(body, dict):
        return result
    for field in ("actions", "condition_updates"):
        _resolve(body.get(field), available, narration)
    return type(result).model_validate(body) if isinstance(result, BaseModel) else body


def _resolve(entries: Any, available: dict[str, str], narration: str) -> None:
    if not isinstance(entries, list):
        return
    for entry in entries:
        value = entry.get("evidence") if isinstance(entry, dict) else None
        if not isinstance(value, str) or value in narration:
            continue
        text = available.get(value)
        if text is not None and len(text) >= 4:
            entry["evidence"] = text
