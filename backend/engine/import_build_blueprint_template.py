"""Map blueprint metadata to template fields without applying session-bundle defaults."""

from backend.models.adventure_template import AdventureTemplate
from backend.utils.text_utils import generate_adventure_id


def build_blueprint_template(
    payload, manifest, adv_meta, owner_id, origin_id, enforcement_mode, is_strict
):
    from backend.engine.adventure_importer import _resolve_license_url

    return AdventureTemplate(
        id=generate_adventure_id(
            adv_meta.get("title") or manifest.get("title") or "Imported Blueprint"
        ),
        owner_id=owner_id,
        title=adv_meta.get("title") or manifest.get("title") or "Imported Blueprint",
        teaser=adv_meta.get("teaser") or manifest.get("teaser"),
        version=adv_meta.get("version") or manifest.get("version"),
        creator=adv_meta.get("creator") or manifest.get("creator"),
        copyright=adv_meta.get("copyright") or manifest.get("copyright"),
        license=adv_meta.get("license") or manifest.get("license"),
        license_url=_resolve_license_url(
            adv_meta.get("license_url") or manifest.get("license_url"),
            adv_meta.get("license") or manifest.get("license"),
        ),
        original_prompt=adv_meta.get("original_prompt")
        or adv_meta.get("context")
        or manifest.get("description")
        or "Restored from blueprint.",
        image_url=adv_meta.get("image_url") or manifest.get("image_url"),
        strict_rules=is_strict,
        rule_enforcement_mode=enforcement_mode,
        time_per_turn=adv_meta.get("time_per_turn", 5),
        pacing_minutes=adv_meta.get("pacing_minutes", 5),
        max_time_per_turn=adv_meta.get("max_time_per_turn") or manifest.get("max_time_per_turn"),
        max_memory_turns=adv_meta.get("max_memory_turns") or manifest.get("max_memory_turns") or 10,
        clock_enabled=adv_meta.get("clock_enabled", False),
        selected_image_styles=adv_meta.get("selected_image_styles")
        or manifest.get("selected_image_styles", []),
        selected_tone=adv_meta.get("selected_tone") or manifest.get("selected_tone"),
        quests=adv_meta.get("quests") or manifest.get("quests") or [],
        awards=adv_meta.get("awards") or manifest.get("awards") or [],
        original_manifest=manifest,
        plot=adv_meta.get("plot") or manifest.get("plot"),
        rules=adv_meta.get("rules") or manifest.get("rules"),
        intro_text=adv_meta.get("intro_text") or manifest.get("intro_text"),
        walkthrough=adv_meta.get("walkthrough") or manifest.get("walkthrough"),
        completed_condition=adv_meta.get("completed_condition")
        or manifest.get("completed_condition"),
        gameover_condition=adv_meta.get("gameover_condition") or manifest.get("gameover_condition"),
        completed_guard_expression=adv_meta.get("completed_guard_expression")
        or manifest.get("completed_guard_expression"),
        gameover_guard_expression=adv_meta.get("gameover_guard_expression")
        or manifest.get("gameover_guard_expression"),
        tts_director_notes=adv_meta.get("tts_director_notes") or manifest.get("tts_director_notes"),
        starting_timestamp=adv_meta.get("starting_timestamp")
        or manifest.get("starting_timestamp", 0),
        time_system=adv_meta.get("time_system") or manifest.get("time_system", "calendar"),
        time_config=adv_meta.get("time_config") or manifest.get("time_config"),
        allow_dynamic_items=adv_meta.get("allow_dynamic_items", False)
        if "allow_dynamic_items" in adv_meta
        else (manifest.get("allow_dynamic_items", False)),
        can_damage_npcs=adv_meta.get("can_damage_npcs", True)
        if "can_damage_npcs" in adv_meta
        else (manifest.get("can_damage_npcs", True)),
        npcs_can_damage_protagonist=adv_meta.get("npcs_can_damage_protagonist", True)
        if "npcs_can_damage_protagonist" in adv_meta
        else (manifest.get("npcs_can_damage_protagonist", True)),
        cover_source_adventure_id=adv_meta.get("cover_source_adventure_id")
        or manifest.get("cover_source_adventure_id"),
        cover_source_adventure_name=adv_meta.get("cover_source_adventure_name")
        or manifest.get("cover_source_adventure_name"),
        cover_similarity_percent=(
            adv_meta.get("cover_similarity_percent")
            if "cover_similarity_percent" in adv_meta
            else manifest.get("cover_similarity_percent", 50)
        ),
        allow_reuse_source_assets=adv_meta.get("allow_reuse_source_assets", True)
        if "allow_reuse_source_assets" in adv_meta
        else manifest.get("allow_reuse_source_assets", True),
        min_scenes=adv_meta.get("min_scenes")
        if adv_meta.get("min_scenes") is not None
        else manifest.get("min_scenes"),
        max_scenes=adv_meta.get("max_scenes")
        if adv_meta.get("max_scenes") is not None
        else manifest.get("max_scenes"),
        min_items=adv_meta.get("min_items")
        if adv_meta.get("min_items") is not None
        else manifest.get("min_items"),
        max_items=adv_meta.get("max_items")
        if adv_meta.get("max_items") is not None
        else manifest.get("max_items"),
        container_generation_enabled=adv_meta.get("container_generation_enabled", True)
        if "container_generation_enabled" in adv_meta
        else manifest.get("container_generation_enabled", True),
        scripts_generation_enabled=adv_meta.get("scripts_generation_enabled", False)
        if "scripts_generation_enabled" in adv_meta
        else manifest.get("scripts_generation_enabled", False),
        min_containers=adv_meta.get("min_containers")
        if adv_meta.get("min_containers") is not None
        else manifest.get("min_containers"),
        max_containers=adv_meta.get("max_containers")
        if adv_meta.get("max_containers") is not None
        else manifest.get("max_containers"),
        text_log_generation_enabled=adv_meta.get("text_log_generation_enabled", True)
        if "text_log_generation_enabled" in adv_meta
        else manifest.get("text_log_generation_enabled", True),
        min_text_logs=adv_meta.get("min_text_logs")
        if adv_meta.get("min_text_logs") is not None
        else manifest.get("min_text_logs"),
        max_text_logs=adv_meta.get("max_text_logs")
        if adv_meta.get("max_text_logs") is not None
        else manifest.get("max_text_logs"),
        min_quests=adv_meta.get("min_quests")
        if adv_meta.get("min_quests") is not None
        else manifest.get("min_quests"),
        max_quests=adv_meta.get("max_quests")
        if adv_meta.get("max_quests") is not None
        else manifest.get("max_quests"),
        quest_generation_enabled=adv_meta.get("quest_generation_enabled", True)
        if "quest_generation_enabled" in adv_meta
        else manifest.get("quest_generation_enabled", True),
        min_awards=adv_meta.get("min_awards")
        if adv_meta.get("min_awards") is not None
        else manifest.get("min_awards"),
        max_awards=adv_meta.get("max_awards")
        if adv_meta.get("max_awards") is not None
        else manifest.get("max_awards"),
        award_generation_enabled=adv_meta.get("award_generation_enabled", False)
        if "award_generation_enabled" in adv_meta
        else manifest.get("award_generation_enabled", False),
        language=adv_meta.get("language") or manifest.get("language"),
        origin_id=origin_id,
        is_adventure_generator=adv_meta.get("is_adventure_generator", False),
        is_ready=True,
        creation_status="Ready",
    )
