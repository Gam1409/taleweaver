"""Portable story identity, independent of display titles and storage paths."""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5


def normalize_origin_id(value: Any) -> str:
    """Canonicalize UUID spelling while preserving existing legacy keys exactly."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Story identity must be a nonempty string.")
    try:
        return str(UUID(value))
    except ValueError:
        return value


def stable_origin_id(template: Any) -> str:
    """Preserve an imported identity; give older local templates a repeatable UUID."""
    if template.origin_id:
        return str(template.origin_id)
    return str(uuid5(NAMESPACE_URL, f"taleweaver:adventure:{template.id}"))
