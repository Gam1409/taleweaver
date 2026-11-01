"""Explicit session-wide movement changes and template restriction synchronization."""

from sqlalchemy import select

from backend.models.world_entity import WorldEntity


async def debug_moveable(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split()
    if len(parts) != 3 or parts[2].lower() not in {"true", "false", "1", "0", "yes", "no"}:
        return "DEBUG ERROR: Usage: /debug moveable [NPC_ID|NAME|all] [true|false]"
    target = parts[1]
    enabled = parts[2].lower() in {"true", "1", "yes"}
    entities = list(
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC"
            )
        )
    )
    selected = (
        entities
        if target.lower() == "all"
        else [
            entity
            for entity in entities
            if entity.id.upper() == target.upper() or (entity.name or "").lower() == target.lower()
        ][:1]
    )
    if not selected:
        return f"DEBUG ERROR: NPC '{target}' not found in session."
    templates = {}
    if target.lower() == "all" and enabled and state.template_id:
        rows = await db.scalars(
            select(WorldEntity).where(
                WorldEntity.template_id == state.template_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.entity_type == "NPC",
            )
        )
        templates = {entity.id: entity for entity in rows}
    states = dict(state.entity_states or {})
    for entity in selected:
        override = {**states.get(entity.id, {}), "moveable": enabled}
        if entity.id in templates:
            override["allowed_scenes"] = list(templates[entity.id].allowed_scenes or [])
        states[entity.id] = override
    state.entity_states = states
    await db.commit()
    if target.lower() != "all":
        return f"DEBUG: NPC '{selected[0].name}' moveable set to {enabled}."
    return (
        f"DEBUG: Movement {'enabled' if enabled else 'disabled'} for {len(selected)} NPCs. "
        f"Scene restrictions refreshed from the adventure for {len(templates.keys() & {e.id for e in selected})} NPCs. "
        "Generated locations are accessible to movable NPCs by default."
    )
