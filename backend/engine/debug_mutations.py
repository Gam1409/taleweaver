from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.models.world_entity import WorldEntity


async def debug_log(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) >= 2:
        cmd = parts[1].lower()
        if cmd == "on":
            state.is_debug_enabled = True
            return "[DEBUG_LOG_ON] Technical logging enabled. You will now see GameEvent outcomes in chat."
        elif cmd == "off":
            state.is_debug_enabled = False
            return "[DEBUG_LOG_OFF] Technical logging disabled."


async def debug_on(db, state, args, user=None, adventure=None, avatar=None):
    state.is_debug_enabled = True
    return "[DEBUG_LOG_ON] Technical logging enabled. You will now see GameEvent outcomes in chat."


async def debug_off(db, state, args, user=None, adventure=None, avatar=None):
    state.is_debug_enabled = False
    return "[DEBUG_LOG_OFF] Technical logging disabled."


async def debug_npc(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) >= 2 and parts[1].lower() == "drop_items":
        return "[TRIGGER_NPC_DROP_ITEMS]"
    return "DEBUG ERROR: Usage: /debug npc drop_items"


async def debug_item(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) >= 3 and parts[1].lower() == "dynamic":
        cmd = parts[2].lower()
        if cmd == "on":
            return (
                "DEBUG ERROR: Spontaneous item generation is permanently disabled in this version."
            )
        elif cmd == "off":
            state.allow_dynamic_items = False
            return "[DEBUG_DYNAMIC_ITEMS_OFF] Dynamic item generation disabled for this session."
    return "DEBUG ERROR: Usage: /debug item dynamic [on/off]"


async def debug_delete_item(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug delete_item [ITEM_KEY]"
    item_key = parts[1]
    if not avatar:
        return "DEBUG ERROR: Avatar context missing."

    inv = list(avatar.inventory or [])
    new_inv = [item for item in inv if item.get("id") != item_key and item.get("key") != item_key]
    if len(new_inv) == len(inv):
        return f"DEBUG: Item '{item_key}' not found in inventory."

    avatar.inventory = new_inv
    flag_modified(avatar, "inventory")
    return f"DEBUG: Item '{item_key}' removed from inventory."


async def debug_heal(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug heal [NPC_NAME] [AMOUNT?]"

    # Find the NPC
    amount = None
    try:
        amount = int(parts[-1])
        npc_name = " ".join(parts[1:-1]).lower()
    except ValueError:
        npc_name = " ".join(parts[1:]).lower()

    # Search in session entities
    res = await db.execute(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
    entities = res.scalars().all()
    target = next(
        (e for e in entities if e.name.lower() == npc_name or e.id.lower() == npc_name), None
    )

    if not target:
        return f"DEBUG: NPC/Entity '{npc_name}' not found in this session."

    final_hp = amount if amount is not None else (target.hp or 50)

    # Update state
    overrides = dict(state.entity_states or {})
    if target.id not in overrides:
        overrides[target.id] = {}
    overrides[target.id]["hp"] = final_hp
    state.entity_states = overrides
    flag_modified(state, "entity_states")
    return f"DEBUG: Entity '{target.name}' (ID: {target.id}) restored to {final_hp} HP."


async def debug_unhide(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug unhide [ENTITY_ID|NAME|all]"
    target = " ".join(parts[1:]).strip()

    # If user asked for all, unhide every entity in the session
    if target.lower() == "all":
        res = await db.execute(
            select(WorldEntity).where(WorldEntity.session_id == state.session_id)
        )
        ents = res.scalars().all()
        if not ents:
            return "DEBUG: No entities found in this session."
        states = dict(state.entity_states or {})
        for e in ents:
            if e.id not in states:
                states[e.id] = {}
            states[e.id]["is_hidden"] = False
        state.entity_states = states
        flag_modified(state, "entity_states")
        await db.commit()
        return f"DEBUG: Unhid {len(ents)} entities in this session."

    # Otherwise find specific entity by id or name
    res = await db.execute(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
    ents = res.scalars().all()
    found = None
    for e in ents:
        if e.id == target or (isinstance(e.name, str) and e.name.lower() == target.lower()):
            found = e
            break
    if not found:
        return f"DEBUG: Entity '{target}' not found in this session."
    states = dict(state.entity_states or {})
    if found.id not in states:
        states[found.id] = {}
    states[found.id]["is_hidden"] = False
    state.entity_states = states
    flag_modified(state, "entity_states")
    await db.commit()
    return f"DEBUG: Entity '{found.name}' (ID: {found.id}) is now visible."


async def debug_npc_note(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ", 2)
    if len(parts) < 3:
        return "DEBUG ERROR: Usage: /debug npc_note [NPC_ID|NAME] [note text]"
    target = parts[1].strip()
    note_val = parts[2].strip()

    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC"
        )
    )
    ents = res.scalars().all()
    found = next(
        (
            e
            for e in ents
            if e.id.upper() == target.upper() or (e.name and e.name.lower() == target.lower())
        ),
        None,
    )
    if not found:
        return f"DEBUG ERROR: NPC '{target}' not found in session."

    states = dict(state.entity_states or {})
    if found.id not in states:
        states[found.id] = {}
    states[found.id]["notes"] = note_val
    state.entity_states = states
    flag_modified(state, "entity_states")
    await db.commit()
    return f"DEBUG: NPC '{found.name}' notes set to: \"{note_val}\""


async def debug_moveable(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 3:
        return "DEBUG ERROR: Usage: /debug moveable [NPC_ID|NAME] [true|false]"
    target = parts[1].strip()
    val = parts[2].strip().lower() in ("true", "1", "yes")

    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC"
        )
    )
    ents = res.scalars().all()
    found = next(
        (
            e
            for e in ents
            if e.id.upper() == target.upper() or (e.name and e.name.lower() == target.lower())
        ),
        None,
    )
    if not found:
        return f"DEBUG ERROR: NPC '{target}' not found in session."

    states = dict(state.entity_states or {})
    if found.id not in states:
        states[found.id] = {}
    states[found.id]["moveable"] = val
    state.entity_states = states
    flag_modified(state, "entity_states")
    await db.commit()
    return f"DEBUG: NPC '{found.name}' moveable set to {val}."


async def debug_open_exit(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug open_exit [EXIT_ID]"
    exit_id = parts[1]

    overrides = dict(state.exit_states or {})
    if exit_id not in overrides:
        overrides[exit_id] = {}
    overrides[exit_id]["is_locked"] = False
    state.exit_states = overrides
    flag_modified(state, "exit_states")
    return f"DEBUG: Exit '{exit_id}' is now unlocked."


async def debug_walkthrough(db, state, args, user=None, adventure=None, avatar=None):
    if not state.walkthrough:
        return "DEBUG: No walkthrough available for this adventure."
    return f"[TRIGGER_WALKTHROUGH_REVEAL_FREE] --- DEBUG: WALKTHROUGH ---\n{state.walkthrough}"


async def debug_game_over(db, state, args, user=None, adventure=None, avatar=None):
    return "[TRIGGER_GAME_OVER] Debug: Manual game over trigger."


async def debug_gen_item(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ", 1)
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug gen_item [PROMPT]"
    return f"[TRIGGER_GEN_ITEM] {parts[1]}"
