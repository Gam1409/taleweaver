"""Scripting / trigger instructions for the world builder (LLM world generation).

The trigger catalogue below mirrors what the gameplay engine actually executes:

* Top-level ``scripts`` (see ``WorldScriptSchema``) are dispatched by the script runner
  for ``on_turn_start``, ``on_enter_scene``, ``on_interact`` and ``on_turn_end``.
* Inline ``on_*_script`` / ``on_*_text`` fields on entities are executed by the turn
  state applier (``turn_state_applier.py`` / ``turn_interactions.py``).

Keep this catalogue in sync with ``docs/scripting_engine.md``.
"""

# (trigger, when it fires, target_id meaning)
TOP_LEVEL_TRIGGERS: tuple[tuple[str, str, str], ...] = (
    ("on_turn_start", "before every turn is processed", "None (global)"),
    ("on_enter_scene", "when the protagonist enters a scene", "scene ID (or None for any scene)"),
    (
        "on_interact",
        "when the protagonist examines/attacks/talks to/manipulates an entity",
        "NPC or object ID (or None for any entity)",
    ),
    ("on_turn_end", "after narration and state changes of every turn", "None (global)"),
)

# Entity kind -> ((trigger base name, description), ...). Every base name has a
# `<base>_script` and a `<base>_text` field on the matching schema.
INLINE_TRIGGERS: dict[str, tuple[tuple[str, str], ...]] = {
    "OBJECTS": (
        ("on_pickup", "the item is taken into the inventory"),
        ("on_drop", "the item is dropped"),
        ("on_equip", "the item is equipped (only WEAPON/WEARABLE items)"),
        ("on_unequip", "the item is unequipped (only WEAPON/WEARABLE items)"),
        ("on_read", "the readable item is inspected or read (only READABLE items)"),
        ("on_unlock_success", "container is successfully unlocked (only CONTAINER items)"),
        (
            "on_unlock_failure",
            "container unlock fails or is blocked by guard (only CONTAINER items)",
        ),
        ("on_craft_success", "constructable item is crafted (only CONSTRUCTABLE items)"),
        (
            "on_craft_failure",
            "constructable item crafting fails or is blocked by guard (only CONSTRUCTABLE items)",
        ),
    ),
    "SCENES": (
        ("on_enter_scene", "the protagonist enters this scene"),
        ("on_leave_scene", "the protagonist leaves this scene"),
    ),
    "EXITS": (
        ("on_open_exit", "this exit is opened/traversed"),
        ("on_unlock_success", "this exit is successfully unlocked"),
        ("on_unlock_failure", "this exit unlock fails or is blocked by guard"),
    ),
    "NPCS": (
        ("on_defeat", "the NPC is defeated"),
        ("on_protagonist_enters_scene", "the protagonist enters the scene containing this NPC"),
    ),
    "PROTAGONIST": (
        ("on_hp_change", "the protagonist HP changes (e.g. damaged or healed)"),
        ("on_status_change", "the protagonist status effects change"),
    ),
    "SEQUENCES": (
        ("on_start_sequence", "this chapter sequence becomes active"),
        ("on_end_sequence", "this chapter sequence is completed"),
    ),
}

# `tw` API reference. Only members that exist in engine/scripting/context.py.
TW_API_REFERENCE = (
    "AVAILABLE `tw` API (use ONLY these members, scripts run in a sandbox):\n"
    "- tw.player: hp, mana, stamina, xp, name | damage(n), heal(n), modify_hp/mana/stamina/xp(delta), "
    "give_item(item_id, name=None, description=None), remove_item(item_id), has_item(item_id), "
    "add_status_effect(name), remove_status_effect(name), has_status_effect(name)\n"
    "- tw.scene: id, npcs, items | teleport(scene_id)\n"
    "- tw.exits: is_locked(from_scene_id, to_scene_id), lock(from_scene_id, to_scene_id, reason), "
    "unlock(from_scene_id, to_scene_id)  (ALWAYS pass the two scene IDs of the exit)\n"
    "- tw.npcs / tw.objects (alias tw.items): get(id), exists(id), say(id, text), move(id, scene_id), "
    "move_to_player(id), kill(id), give_item(npc_id, item_id), drop_item(npc_id, item_id, scene_id=None)\n"
    "- entity proxies from get(): id, name, current_scene_id, is_hidden, set_hidden(bool); NPCs also hp, is_defeated, say(text); "
    "objects also state, switch_state, flip(), toggle()\n"
    "- tw.switches: get(id), get_state(id, default), set_state(id, new_state, apply_outcomes=True), "
    "is_state(id, state), flip(id, apply_outcomes=True), toggle(id, apply_outcomes=True) | switch proxies from get() or tw.switch(id): id, state, switch_state, states, initial_state, flip(), toggle()\n"
    "- tw.vars: get(key, default), set(key, value)  (persistent story flags)\n"
    "- tw.story: narrate(text) / show_message(text), system_message(text), reject_action(reason)\n"
    "- tw.memories.add(description, scope='global'|'local', emotion='positive'|'negative'|'neutral')\n"
    "- tw.quests: complete(quest_id), fail(quest_id), is_completed(quest_id)\n"
    "- tw.awards.grant(award_key) | tw.sequences.advance() | tw.dice.d20()\n"
    "- tw.game: time | win(reason), game_over(reason)\n"
)

_EXAMPLES = (
    "VALID EXAMPLES:\n"
    "1. Trap on interact (top-level: trigger='on_interact', target_id='CHEST_01'):\n"
    "   if not tw.vars.get('trap_disarmed', False):\\n"
    "       tw.player.damage(15)\\n"
    "       tw.story.show_message('A poisoned needle springs from the lock mechanism! (-15 HP)')\n"
    "2. Gatekeeper on enter scene (top-level: trigger='on_enter_scene', target_id='SCENE_GATES'):\n"
    "   if not tw.player.has_item('ITEM_KEY'):\\n"
    "       tw.exits.lock('SCENE_GATES', 'SCENE_COURTYARD', 'The heavy iron portcullis is barred.')\\n"
    "       tw.story.show_message('The sentinel lowers his spear, barring the passage.')\\n"
    "   else:\\n"
    "       tw.exits.unlock('SCENE_GATES', 'SCENE_COURTYARD')\n"
    "3. Cursed weapon (inline on the object: on_equip_script):\n"
    "   tw.player.damage(5)\\n"
    "   tw.story.show_message('The blade burns your palm as you grip it.')\n"
    "4. Boss loot (inline on the NPC: on_defeat_script):\n"
    "   tw.player.give_item('ITEM_BOSS_KEY')\\n"
    "   tw.story.show_message('The warlord drops a heavy iron key.')\n"
    "5. Atmosphere only (inline `..._text` field, no code): on_enter_scene_text = "
    "'A cold draft carries the smell of old blood.'\n"
    "6. Switch activation (inline on switch: on_success_script):\n"
    "   tw.exits.unlock('SCENE_LAB', 'SCENE_VAULT')\n"
    "   tw.story.show_message('A loud click echoes through the vault corridors.')\n"
    "7. Secret document on read (inline on READABLE object: on_read_script):\n"
    "   tw.vars.set('read_secret_plans', True)\n"
    "   tw.story.show_message('You memorize the classified blueprints.')\n"
    "8. Container unlock guard (inline on CONTAINER object: unlock_expression & on_unlock_success_script):\n"
    "   unlock_expression = \"tw.switches.get('POWER_CORE') == 'ACTIVE'\"\n"
    "   on_unlock_success_script = \"tw.story.show_message('The cryo-chamber decompresses with a hiss.')\"\n"
)


def _top_level_trigger_lines() -> str:
    return "".join(
        f"  - `{name}`: {when}; `target_id` = {target}\n"
        for name, when, target in TOP_LEVEL_TRIGGERS
    )


def _inline_trigger_lines() -> str:
    lines = []
    for kind, triggers in INLINE_TRIGGERS.items():
        fields = ", ".join(f"`{base}_script`, `{base}_text`" for base, _ in triggers)
        whens = "; ".join(f"{base}: {desc}" for base, desc in triggers)
        lines.append(f"- {kind}: {fields}  ({whens})\n")
    return "".join(lines)


def build_scripts_requirement(scripts_generation_enabled: bool) -> str:
    """Return the scripting section appended to the world generation user prompt."""
    if not scripts_generation_enabled:
        return (
            "\nSCRIPTING: Do NOT generate any custom scripts. Keep scripts: [] and do not "
            "populate any on_*_script or on_*_text fields (leave them as empty strings)."
        )
    separator = "=" * 80
    return (
        f"\n\n{separator}\n"
        "CRITICAL DIRECTIVE - EVENT SCRIPTS ACTIVELY REQUESTED BY USER:\n"
        "The user has explicitly turned ON the Event Scripts Engine for this adventure. "
        "The world MUST contain interactive event scripts!\n\n"
        "1) TOP-LEVEL SCRIPTS: generate between 1 and 3 high-quality, deterministic scripts in the "
        "top-level `scripts` array. Each has `id` (unique uppercase slug, e.g. 'SCRIPT_TRAP_CHEST'), "
        "`name`, `trigger`, `target_id`, `code` and optional `description`. "
        "`trigger` must be EXACTLY one of:\n"
        f"{_top_level_trigger_lines()}\n"
        "2) INLINE TRIGGERS: you MUST ALSO attach inline triggers directly to entities. Every trigger has a "
        "`..._text` field (prints a fixed message) and a `..._script` field (runs `tw` code). "
        "Use an empty string for every trigger you do not need. Fill the following fields where they fit "
        "the story (aim for several across different entity kinds, e.g. a cursed item, a guarded scene, "
        "a boss that drops loot):\n"
        f"{_inline_trigger_lines()}\n"
        "RULES:\n"
        "- Only reference scene/exit/NPC/object/quest IDs that exist in this manifest.\n"
        "- Prefer `..._text` for pure flavour, `..._script` for mechanics (damage, items, locks, flags).\n"
        "- Keep inline scripts short (max ~10 lines); never use imports, file/network access or loops over huge ranges.\n"
        "- `on_equip_*`/`on_unequip_*` are only meaningful for WEAPON/WEARABLE objects.\n"
        "- Scripts must be consistent with the walkthrough: they must never make the adventure unwinnable.\n\n"
        f"{TW_API_REFERENCE}\n"
        f"{_EXAMPLES}"
        f"{separator}\n"
    )
