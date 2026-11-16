"""Narration gets visible clothing facts; private wardrobe stays with the continuity pass."""

import json
from typing import Any

from backend.engine.clothing.context import actor_records, detail_settings
from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.visuals import character_visuals
from backend.engine.physical_conditions.presentation import narration_block
from backend.engine.physical_conditions.scope import item_scope
from backend.engine.visual_novel.continuity import PLAYER


class _NarratedNPC:
    def __init__(self, entity: Any, visual: dict | None):
        self._entity = entity
        self.inventory: list[dict[str, Any]] = []
        self.description = entity.description
        if visual is not None:
            self.description = "; ".join(
                str(visual.get(key) or "") for key in ("appearance", "clothing")
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entity, name)


def _known_placements(actor: dict, detailed: bool) -> list[dict]:
    profile = load_profile(actor.get("visual_profile"))
    if profile is None:
        return []
    items = owned_items(actor["resolved_inventory"], equipment=actor.get("equipment"))
    age = profile.appearance.age_years
    adult = age is not None and age >= 18
    result = []
    for worn in profile.worn:
        if worn.item_id not in items or not (worn.uncovered_regions or worn.attachment_slot):
            continue
        if worn.source is None and actor["id"] != PLAYER:
            continue
        garment = garment_for_item(items[worn.item_id])
        if (worn.attachment_slot and not adult) or (
            garment and garment.underwear and not (adult and detailed)
        ):
            continue
        result.append(
            {
                "item_id": worn.item_id,
                "name": items[worn.item_id].get("name", ""),
                "uncovered_regions": worn.uncovered_regions,
                **({"attachment_slot": worn.attachment_slot} if worn.attachment_slot else {}),
            }
        )
    return result


def narration_clothing(
    manager: Any,
    visible: list[Any],
    all_entities: list[Any],
    *,
    item_entities: list[Any] | None = None,
) -> tuple[list[Any], str]:
    actors = actor_records(manager, all_entities)
    detailed = detail_settings(manager)["detailed"]
    visuals = {
        actor_id: character_visuals(actor, actor["resolved_inventory"], detailed=detailed)
        for actor_id, actor in actors.items()
    }
    for actor_id, actor in actors.items():
        visual = visuals.get(actor_id)
        if visual is None:
            continue
        placements = _known_placements(actor, detailed)
        if placements:
            visual["known_worn_placements"] = placements
    entities = [
        _NarratedNPC(entity, visuals.get(entity.id)) if entity.entity_type == "NPC" else entity
        for entity in visible
    ]
    facts = [visual for visual in visuals.values() if visual is not None]
    scope = item_scope(
        manager, item_entities if item_entities is not None else all_entities, visible=visible
    )
    conditions = narration_block(
        manager.state,
        actors,
        detailed=detailed,
        visible_item_ids=set(scope.public_ids),
    )
    if not facts:
        return entities, conditions
    return entities, (
        "\nAUTHORITATIVE CURRENT APPEARANCE AND VISIBLE CLOTHING:\n"
        + json.dumps(facts, ensure_ascii=False)
        + "\nThese current facts supersede outfits in historical dialogue, biography and prior images. "
        "Describe only visible layers. Carried possessions are not automatically worn. "
        "known_worn_placements preserves established item positions through displacement or "
        "occlusion. Retain those positions without treating them as a new visual observation "
        "or inferring that other garments are absent. "
        "Unspecified clothing does not establish undress or reveal hidden garments. "
        "The continuity outcome decides changes; do not invent new clothes or clothing actions.\n"
        + conditions
    )
