"""Read legacy and current ComfyUI combo schemas without inventing missing choices."""

from typing import Any


def combo_choices(spec: Any) -> list[Any] | None:
    """None means unknown choices; an explicit empty list means none are installed."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    first = spec[0]
    if isinstance(first, (list, tuple)):
        return list(first)
    if first != "COMBO" or len(spec) < 2 or not isinstance(spec[1], dict):
        return None
    choices = spec[1].get("options")
    return list(choices) if isinstance(choices, (list, tuple)) else None
