"""Editor garment metadata: explicit changes only, with no ownership or wear mutation."""

from typing import Any

from backend.engine.clothing.schema import Garment

GARMENT_INSTRUCTION = """
For WEARABLE items supply clothing metadata as well as equipment slots.
Choose category clothing, armor, or accessory. A necklace, ring or small ornament is
an accessory: it never hides an entire body region's lower clothing. Clothing and armor
may block lower layers when opaque=true. Category armor does not grant combat stats.
layer is 0..4 from innermost to outermost; use the description to distinguish a shirt
from an overcoat, not just its equipment slot. A visible ornament over clothing belongs
above that layer. coverage lists covered body regions; for accessories it indicates
placement (necklace: torso, ring: hands) and never whole-region obstruction. A higher
opaque garment can still hide an accessory underneath it. Valid regions are head,
torso, arms, pelvis, legs, feet, hands. Keep clothing.description consistent with the
item's appearance. Do not invent hidden layers or other items. Preserve existing supplied
clothing properties exactly; only fill missing properties. Receiving or owning the item
does not establish wearing it. Return clothing=null for non-WEARABLE item drafts.
"""


def validate_partial_garment(data: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied fields without turning validation placeholders into authored facts."""
    Garment.model_validate({"layer": 2, "coverage": ["torso"], **data})
    return data


def store_editor_clothing(metadata: dict, payload: Any) -> None:
    """Preserve legacy metadata unless the caller explicitly supplied this field."""
    if getattr(payload, "entity_type", "OBJECT") != "OBJECT":
        return
    if "clothing" not in payload.model_fields_set:
        return
    if payload.clothing is None:
        metadata.pop("clothing", None)
        return
    metadata["clothing"] = payload.clothing.model_dump()
