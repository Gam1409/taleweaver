"""Map ADZ metadata to template fields while preserving archive-specific defaults."""

from backend.models.adventure_template import AdventureTemplate


def build_archive_template(
    new_template_id,
    owner_id,
    adv_data,
    manifest_data,
    origin_id,
    enforcement_mode,
    is_strict,
    resolved_license,
    resolved_license_url,
):
    return AdventureTemplate(
        id=new_template_id,
        owner_id=owner_id,
        title=adv_data["title"],
        version=adv_data.get("version"),
        sequences=adv_data.get("sequences") or manifest_data.get("sequences"),
        creator=adv_data.get("creator") or manifest_data.get("creator"),
        copyright=adv_data.get("copyright") or manifest_data.get("copyright"),
        license=resolved_license,
        license_url=resolved_license_url,
        original_prompt=adv_data.get("original_prompt") or adv_data.get("context"),
        strict_rules=is_strict,
        rule_enforcement_mode=enforcement_mode,
        time_per_turn=adv_data.get("time_per_turn", 5),
        pacing_minutes=adv_data.get("pacing_minutes", 5),
        max_time_per_turn=adv_data.get("max_time_per_turn")
        or manifest_data.get("max_time_per_turn"),
        max_memory_turns=adv_data.get("max_memory_turns")
        or manifest_data.get("max_memory_turns")
        or 10,
        clock_enabled=adv_data.get("clock_enabled", False),
        generate_scene_images=adv_data.get("generate_scene_images", False),
        generate_npc_images=adv_data.get("generate_npc_images", False),
        generate_item_images=adv_data.get("generate_item_images", False),
        selected_image_styles=adv_data.get("selected_image_styles")
        or manifest_data.get("selected_image_styles", []),
        selected_tone=adv_data.get("selected_tone") or manifest_data.get("selected_tone"),
        quests=adv_data.get("quests") or manifest_data.get("quests", []),
        awards=adv_data.get("awards") or manifest_data.get("awards", []),
        min_scenes=(
            int(adv_data["min_scenes"])
            if adv_data.get("min_scenes") is not None
            else (
                int(manifest_data["min_scenes"])
                if manifest_data.get("min_scenes") is not None
                else None
            )
        ),
        max_scenes=(
            int(adv_data["max_scenes"])
            if adv_data.get("max_scenes") is not None
            else (
                int(manifest_data["max_scenes"])
                if manifest_data.get("max_scenes") is not None
                else None
            )
        ),
        min_items=(
            int(adv_data["min_items"])
            if adv_data.get("min_items") is not None
            else (
                int(manifest_data["min_items"])
                if manifest_data.get("min_items") is not None
                else None
            )
        ),
        max_items=(
            int(adv_data["max_items"])
            if adv_data.get("max_items") is not None
            else (
                int(manifest_data["max_items"])
                if manifest_data.get("max_items") is not None
                else None
            )
        ),
        container_generation_enabled=(
            adv_data.get("container_generation_enabled", True)
            if "container_generation_enabled" in adv_data
            else manifest_data.get("container_generation_enabled", True)
        ),
        scripts_generation_enabled=(
            adv_data.get("scripts_generation_enabled", False)
            if "scripts_generation_enabled" in adv_data
            else manifest_data.get("scripts_generation_enabled", False)
        ),
        min_containers=(
            int(adv_data["min_containers"])
            if adv_data.get("min_containers") is not None
            else (
                int(manifest_data["min_containers"])
                if manifest_data.get("min_containers") is not None
                else None
            )
        ),
        max_containers=(
            int(adv_data["max_containers"])
            if adv_data.get("max_containers") is not None
            else (
                int(manifest_data["max_containers"])
                if manifest_data.get("max_containers") is not None
                else None
            )
        ),
        text_log_generation_enabled=(
            adv_data.get("text_log_generation_enabled", True)
            if "text_log_generation_enabled" in adv_data
            else manifest_data.get("text_log_generation_enabled", True)
        ),
        min_text_logs=(
            int(adv_data["min_text_logs"])
            if adv_data.get("min_text_logs") is not None
            else (
                int(manifest_data["min_text_logs"])
                if manifest_data.get("min_text_logs") is not None
                else None
            )
        ),
        max_text_logs=(
            int(adv_data["max_text_logs"])
            if adv_data.get("max_text_logs") is not None
            else (
                int(manifest_data["max_text_logs"])
                if manifest_data.get("max_text_logs") is not None
                else None
            )
        ),
        min_quests=(
            int(adv_data["min_quests"])
            if adv_data.get("min_quests") is not None
            else (
                int(manifest_data["min_quests"])
                if manifest_data.get("min_quests") is not None
                else None
            )
        ),
        max_quests=(
            int(adv_data["max_quests"])
            if adv_data.get("max_quests") is not None
            else (
                int(manifest_data["max_quests"])
                if manifest_data.get("max_quests") is not None
                else None
            )
        ),
        quest_generation_enabled=(
            adv_data.get("quest_generation_enabled", True)
            if "quest_generation_enabled" in adv_data
            else manifest_data.get("quest_generation_enabled", True)
        ),
        min_awards=(
            int(adv_data["min_awards"])
            if adv_data.get("min_awards") is not None
            else (
                int(manifest_data["min_awards"])
                if manifest_data.get("min_awards") is not None
                else None
            )
        ),
        max_awards=(
            int(adv_data["max_awards"])
            if adv_data.get("max_awards") is not None
            else (
                int(manifest_data["max_awards"])
                if manifest_data.get("max_awards") is not None
                else None
            )
        ),
        award_generation_enabled=(
            adv_data.get("award_generation_enabled", False)
            if "award_generation_enabled" in adv_data
            else manifest_data.get("award_generation_enabled", False)
        ),
        plot=adv_data.get("plot") or manifest_data.get("plot"),
        rules=adv_data.get("rules") or manifest_data.get("rules"),
        intro_text=adv_data.get("intro_text") or manifest_data.get("intro_text"),
        walkthrough=adv_data.get("walkthrough") or manifest_data.get("walkthrough"),
        completed_condition=adv_data.get("completed_condition")
        or manifest_data.get("completed_condition"),
        gameover_condition=adv_data.get("gameover_condition")
        or manifest_data.get("gameover_condition"),
        completed_guard_expression=adv_data.get("completed_guard_expression")
        or manifest_data.get("completed_guard_expression"),
        gameover_guard_expression=adv_data.get("gameover_guard_expression")
        or manifest_data.get("gameover_guard_expression"),
        tts_director_notes=adv_data.get("tts_director_notes")
        or manifest_data.get("tts_director_notes"),
        starting_timestamp=adv_data.get("starting_timestamp")
        or manifest_data.get("starting_timestamp", 0),
        time_system=adv_data.get("time_system") or manifest_data.get("time_system", "calendar"),
        time_config=adv_data.get("time_config") or manifest_data.get("time_config"),
        game_over_rules=adv_data.get("game_over_rules") or manifest_data.get("game_over_rules"),
        allow_dynamic_items=adv_data.get("allow_dynamic_items", False)
        if "allow_dynamic_items" in adv_data
        else (manifest_data.get("allow_dynamic_items", False)),
        can_damage_npcs=adv_data.get("can_damage_npcs", True)
        if "can_damage_npcs" in adv_data
        else (manifest_data.get("can_damage_npcs", True)),
        npcs_can_damage_protagonist=adv_data.get("npcs_can_damage_protagonist", True)
        if "npcs_can_damage_protagonist" in adv_data
        else (manifest_data.get("npcs_can_damage_protagonist", True)),
        cover_source_adventure_id=adv_data.get("cover_source_adventure_id")
        or manifest_data.get("cover_source_adventure_id"),
        cover_source_adventure_name=adv_data.get("cover_source_adventure_name")
        or manifest_data.get("cover_source_adventure_name"),
        cover_similarity_percent=(
            adv_data.get("cover_similarity_percent")
            if "cover_similarity_percent" in adv_data
            else manifest_data.get("cover_similarity_percent", 50)
        ),
        allow_reuse_source_assets=adv_data.get("allow_reuse_source_assets", True)
        if "allow_reuse_source_assets" in adv_data
        else manifest_data.get("allow_reuse_source_assets", True),
        is_adventure_generator=adv_data.get("is_adventure_generator", False)
        or manifest_data.get("is_adventure_generator", False),
        is_ready=True,
        creation_status="Ready",
        original_manifest=manifest_data,
        language=adv_data.get("language") or manifest_data.get("language"),
        origin_id=origin_id,
    )
