"""Reconstruct world fields from an ADZ manifest without changing its defaults."""


def build_archive_world(manifest_data, adv_data, resolved_license_url):
    # Reconstruct world
    prot = manifest_data.get("protagonist")
    world_manifest = {
        "protagonist": {
            "name": prot.get("name", "You") if prot else "You",
            "role": prot.get("role", "Hero") if prot else "Hero",
            "description": prot.get("description", "") if prot else "",
            "profile_image": prot.get("profile_image") if prot else None,
            "hp": prot.get("hp", 200) if prot else 200,
            "max_hp": prot.get("max_hp", prot.get("hp", 200)) if prot else 200,
            "stamina": prot.get("stamina", 200) if prot else 200,
            "max_stamina": prot.get("max_stamina", prot.get("stamina", 200)) if prot else 200,
            "mana": prot.get("mana", 200) if prot else 200,
            "max_mana": prot.get("max_mana", prot.get("mana", 200)) if prot else 200,
            "strength": prot.get("strength", 10) if prot else 10,
            "dexterity": prot.get("dexterity", 10) if prot else 10,
            "intelligence": prot.get("intelligence", 10) if prot else 10,
            "wisdom": prot.get("wisdom", 10) if prot else 10,
            "charisma": prot.get("charisma", 10) if prot else 10,
            "armor_class": prot.get("armor_class", 10) if prot else 10,
            "exp": prot.get("exp", 0) if prot else 0,
            "goal": prot.get("goal", "") if prot else "",
            "character": prot.get("character", "") if prot else "",
            "status_effects": prot.get("status_effects", []) if prot else [],
            "stats": prot.get("stats", {}) if prot else {},
            "starting_inventory": prot.get("starting_inventory", prot.get("inventory", []))
            if prot
            else [],
            "starting_equipment": prot.get("starting_equipment", prot.get("equipment", {}))
            if prot
            else {},
        },
        "scenes": manifest_data.get("scenes", []),
        "exits": manifest_data.get("exits", []),
        "npcs": manifest_data.get("npcs", []),
        "objects": manifest_data.get("objects", []),
        "sequences": adv_data.get("sequences") or manifest_data.get("sequences", []),
        "quests": manifest_data.get("quests") or adv_data.get("quests", []),
        "awards": manifest_data.get("awards") or adv_data.get("awards", []),
        "teaser": manifest_data.get("teaser") or adv_data.get("teaser"),
        "intro_text": manifest_data.get("intro_text") or adv_data.get("intro_text"),
        "plot": manifest_data.get("plot") or adv_data.get("plot"),
        "rules": manifest_data.get("rules") or adv_data.get("rules"),
        "walkthrough": manifest_data.get("walkthrough") or adv_data.get("walkthrough"),
        "completed_condition": manifest_data.get("completed_condition")
        or adv_data.get("completed_condition"),
        "gameover_condition": manifest_data.get("gameover_condition")
        or adv_data.get("gameover_condition"),
        "completed_guard_expression": manifest_data.get("completed_guard_expression")
        or adv_data.get("completed_guard_expression"),
        "gameover_guard_expression": manifest_data.get("gameover_guard_expression")
        or adv_data.get("gameover_guard_expression"),
        "tts_director_notes": manifest_data.get("tts_director_notes")
        or adv_data.get("tts_director_notes"),
        "creator": adv_data.get("creator") or manifest_data.get("creator"),
        "copyright": adv_data.get("copyright") or manifest_data.get("copyright"),
        "license": adv_data.get("license") or manifest_data.get("license"),
        "license_url": resolved_license_url,
    }

    default_scene_id = manifest_data["scenes"][0]["id"] if manifest_data.get("scenes") else "START"
    for n in world_manifest["npcs"]:
        if "start_scene_id" not in n:
            n["start_scene_id"] = n.get("current_scene_id") or default_scene_id
    for o in world_manifest["objects"]:
        if "start_scene_id" not in o:
            o["start_scene_id"] = o.get("current_scene_id") or default_scene_id

    return world_manifest
