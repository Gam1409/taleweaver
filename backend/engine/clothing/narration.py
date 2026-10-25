"""Narration gets visible clothing facts; private wardrobe stays with the continuity pass."""

import json
from typing import Any

from backend.engine.clothing.context import actor_records, detail_settings
from backend.engine.clothing.visuals import character_visuals


class _NarratedNPC:
    def __init__(self, entity: Any, visual: dict | None):
        self._entity = entity
        self.inventory = []
        self.description = entity.description
        if visual is not None:
            self.description = "; ".join(
                str(visual.get(key) or "") for key in ("appearance", "clothing")
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entity, name)


def narration_clothing(
    manager: Any, visible: list[Any], all_entities: list[Any]
) -> tuple[list[Any], str]:
    actors = actor_records(manager, all_entities)
    detailed = detail_settings(manager)["detailed"]
    visuals = {
        actor_id: character_visuals(actor, actor["resolved_inventory"], detailed=detailed)
        for actor_id, actor in actors.items()
    }
    entities = [
        _NarratedNPC(entity, visuals.get(entity.id)) if entity.entity_type == "NPC" else entity
        for entity in visible
    ]
    facts = [visual for visual in visuals.values() if visual is not None]
    if not facts:
        return entities, ""
    return entities, (
        "\nAUTHORITATIVE CURRENT APPEARANCE AND VISIBLE CLOTHING:\n"
        + json.dumps(facts, ensure_ascii=False)
        + "\nThese current facts supersede outfits in historical dialogue, biography and prior images. "
        "Describe only visible layers. Carried possessions are not automatically worn. "
        "Unspecified clothing does not establish undress or reveal hidden garments. "
        "The continuity outcome decides changes; do not invent new clothes or clothing actions.\n"
    )
