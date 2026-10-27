from datetime import datetime

from sqlalchemy import select

from backend.engine.map_engine import MapEngine
from backend.models.adventure_template import AdventureTemplate
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene


async def debug_szene(db, state, args, user=None, adventure=None, avatar=None):
    scene_id = state.scene_id
    res = await db.execute(
        select(WorldScene).where(
            WorldScene.id == scene_id, WorldScene.session_id == state.session_id
        )
    )
    scene = res.scalars().first()
    if not scene:
        return f"DEBUG ERROR: Scene '{scene_id}' not found in session manifest."

    return (
        f"--- DEBUG: SCENE [{scene_id}] ---\nLabel: {scene.label}\nDescription: {scene.description}"
    )


async def debug_entities(db, state, args, user=None, adventure=None, avatar=None):
    scene_id = state.scene_id
    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.current_scene_id == scene_id, WorldEntity.session_id == state.session_id
        )
    )
    entities = res.scalars().all()

    overrides = state.entity_states or {}
    processed = []
    for e in entities:
        data = {c.name: getattr(e, c.name) for c in e.__table__.columns}
        if e.id in overrides:
            data.update(overrides[e.id])
        processed.append(data)

    if not processed:
        return "--- DEBUG: No entities or objects found in this scene. ---"

    lines = [f"--- DEBUG: ENTITIES IN {scene_id} ---"]
    for e in processed:
        pos = f" @ {e.get('spatial_position')}" if e.get("spatial_position") else ""
        lines.append(
            f"- [{e.get('entity_type')}] {e.get('name')} (ID: {e.get('id')}){pos}: {str(e.get('description', ''))[:50]}..."
        )
    return "\n".join(lines)


async def debug_plot(db, state, args, user=None, adventure=None, avatar=None):
    adv_id = state.adventure_id
    res = await db.execute(select(AdventureTemplate).where(AdventureTemplate.id == adv_id))
    adv = res.scalars().first()
    return f"--- DEBUG: PLOT CONTEXT ---\n{adv.original_prompt}"


async def debug_map(db, state, args, user=None, adventure=None, avatar=None):
    adv_id = state.adventure_id
    s_count = await db.execute(select(WorldScene).where(WorldScene.session_id == state.session_id))
    e_count = await db.execute(
        select(WorldEntity).where(WorldEntity.session_id == state.session_id)
    )
    ex_count = await db.execute(select(WorldExit).where(WorldExit.session_id == state.session_id))

    return (
        f"--- DEBUG: WORLD STATS ---\n"
        f"AdventureTemplate ID: {adv_id}\n"
        f"Session ID: {state.session_id}\n"
        f"Total Scenes: {len(s_count.scalars().all())}\n"
        f"Total Entities: {len(e_count.scalars().all())}\n"
        f"Total Connections: {len(ex_count.scalars().all())}"
    )


async def debug_session(db, state, args, user=None, adventure=None, avatar=None):
    scene_id = state.scene_id
    res = await db.execute(
        select(WorldScene).where(
            WorldScene.id == scene_id, WorldScene.session_id == state.session_id
        )
    )
    scene = res.scalars().first()
    label = scene.label if scene else "Unknown"

    return (
        f"--- DEBUG: SESSION STATE ---\n"
        f"Session ID: {state.session_id}\n"
        f"Current Scene: {label} (ID: {scene_id})\n"
        f"In-Game Time: {state.in_game_time} minutes\n"
        f"Debug Logging: {'ON' if state.is_debug_enabled else 'OFF'}"
    )


async def debug_engine(db, state, args, user=None, adventure=None, avatar=None):
    import platform
    import sys

    from backend.core.config import settings

    lines = [
        "--- DEBUG: ENGINE DIAGNOSTICS ---",
        f"TaleWeaver Version: {settings.APP_VERSION}",
        f"Platform: {platform.platform()}",
        f"Python Version: {sys.version.split(' ')[0]}",
        f"Server Time: {datetime.now().isoformat()}",
        f"Current Session ID: {state.session_id}",
        f"Debug Mode: {'ENABLED' if settings.TALEWEAVER_DEBUG_ENABLED else 'DISABLED'}",
        f"Data Dir: {settings.DATA_DIR}",
    ]
    return "\n".join(lines)


async def debug_scenes(db, state, args, user=None, adventure=None, avatar=None):
    res = await db.execute(select(WorldScene).where(WorldScene.session_id == state.session_id))
    scenes = res.scalars().all()
    if not scenes:
        return "DEBUG: No scenes found for this session."
    lines = ["--- DEBUG: ALL SCENES ---"]
    for s in scenes:
        lines.append(f"- {s.label} (ID: {s.id})")
    return "\n".join(lines)


async def debug_npcs(db, state, args, user=None, adventure=None, avatar=None):
    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC"
        )
    )
    npcs_db = res.scalars().all()
    if not npcs_db:
        return "--- DEBUG: No NPCs found for this session. ---"

    overrides = state.entity_states or {}
    npcs = []
    for e in npcs_db:
        data = {c.name: getattr(e, c.name) for c in e.__table__.columns}
        if e.id in overrides:
            data.update(overrides[e.id])
        npcs.append(data)

    res_scenes = await db.execute(
        select(WorldScene).where(WorldScene.session_id == state.session_id)
    )
    scene_map = {s.id: s.label for s in res_scenes.scalars().all()}

    lines = ["--- DEBUG: ALL NPCs ---"]
    for n in npcs:
        curr_scene = n.get("current_scene_id")
        loc_label = scene_map.get(curr_scene, curr_scene)
        pos = f" ({n.get('spatial_position')})" if n.get("spatial_position") else ""
        lines.append(f"- {n.get('name')} (ID: {n.get('id')}) @ {loc_label}{pos}")
    return "\n".join(lines)


async def debug_items(db, state, args, user=None, adventure=None, avatar=None):
    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "OBJECT"
        )
    )
    items_db = res.scalars().all()
    if not items_db:
        return "--- DEBUG: No items found for this session. ---"

    overrides = state.entity_states or {}
    items = []
    for e in items_db:
        data = {c.name: getattr(e, c.name) for c in e.__table__.columns}
        if e.id in overrides:
            data.update(overrides[e.id])
        items.append(data)

    res_scenes = await db.execute(
        select(WorldScene).where(WorldScene.session_id == state.session_id)
    )
    scene_map = {s.id: s.label for s in res_scenes.scalars().all()}

    lines = ["--- DEBUG: ALL ITEMS ---"]
    for i in items:
        if i.get("is_in_inventory"):
            loc = "Inventory"
        else:
            curr_scene = i.get("current_scene_id")
            loc_label = scene_map.get(curr_scene, curr_scene)
            pos = f" ({i.get('spatial_position')})" if i.get("spatial_position") else ""
            loc = f"Scene: {loc_label}{pos}"
        lines.append(f"- {i.get('name')} (ID: {i.get('id')}) @ {loc}")
    return "\n".join(lines)


async def debug_exits(db, state, args, user=None, adventure=None, avatar=None):
    res = await db.execute(select(WorldExit).where(WorldExit.session_id == state.session_id))
    exits = res.scalars().all()
    if not exits:
        return "DEBUG: No exits found for this session."
    lines = ["--- DEBUG: ALL EXITS ---"]
    for e in exits:
        locked = "[LOCKED]" if e.is_locked else "[OPEN]"
        lines.append(
            f"- {e.label} (ID: {e.id if hasattr(e, 'id') else 'N/A'}): {e.from_scene_id} -> {e.to_scene_id} {locked}"
        )
    return "\n".join(lines)


async def debug_reveal_map(db, state, args, user=None, adventure=None, avatar=None):
    scenes_res = await db.execute(
        select(WorldScene).where(WorldScene.session_id == state.session_id)
    )
    exits_res = await db.execute(select(WorldExit).where(WorldExit.session_id == state.session_id))

    scenes = list(scenes_res.scalars().all())
    exits = list(exits_res.scalars().all())

    # 2. Also fetch from template to be absolutely sure we have everything
    if state.template_id:
        t_scenes_res = await db.execute(
            select(WorldScene).where(WorldScene.template_id == state.template_id)
        )
        t_exits_res = await db.execute(
            select(WorldExit).where(WorldExit.template_id == state.template_id)
        )

        # Add template scenes/exits if not already in the session list (by ID/label)
        session_scene_ids = {s.id for s in scenes}
        for ts in t_scenes_res.scalars().all():
            if ts.id not in session_scene_ids:
                scenes.append(ts)

        # For exits, we compare from/to/label to avoid duplicates
        session_exits = {(e.from_scene_id, e.to_scene_id, e.label) for e in exits}
        for te in t_exits_res.scalars().all():
            if (te.from_scene_id, te.to_scene_id, te.label) not in session_exits:
                exits.append(te)

    # 3. Get or create the TEMPLATE-LEVEL map — this is what the frontend always reads
    from backend.api.routes.adventures.logic import AdventureLogic

    world_map = await AdventureLogic.get_or_create_map(db, state.template_id)

    # 4. Register everything
    for s in scenes:
        MapEngine.register_visit(
            world_map, s.id, label=s.label, description=s.description, image_url=s.image_url
        )

    # 5. Restore the actual current position
    world_map.current_scene_id = MapEngine._safe_id(state.scene_id)

    for e in exits:
        MapEngine.register_exit(
            world_map, e.from_scene_id, e.to_scene_id, exit_label=e.label, is_locked=e.is_locked
        )

    return "DEBUG: World Map fully revealed and synchronized."
