"""Portable story identity, independent of display titles and storage paths."""

from typing import Any
from uuid import NAMESPACE_URL, uuid5


def stable_origin_id(template: Any) -> str:
    """Preserve an imported identity; give older local templates a repeatable UUID."""
    if template.origin_id:
        return str(template.origin_id)
    return str(uuid5(NAMESPACE_URL, f"taleweaver:adventure:{template.id}"))
