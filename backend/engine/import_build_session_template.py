"""Restore template metadata from the adventure section of a session bundle."""

from backend.models.adventure_template import AdventureTemplate
from backend.utils.text_utils import generate_adventure_id


def build_session_template(data, user, origin_id):
    from backend.engine.adventure_importer import _resolve_license_url

    old_adv = data["adventure"]
    return AdventureTemplate(
        id=generate_adventure_id(old_adv["title"]),
        owner_id=user.id,
        title=old_adv["title"],
        teaser=old_adv.get("teaser"),
        version=old_adv.get("version"),
        sequences=old_adv.get("sequences") or data.get("sequences"),
        creator=old_adv.get("creator"),
        copyright=old_adv.get("copyright"),
        license=old_adv.get("license"),
        license_url=_resolve_license_url(old_adv.get("license_url"), old_adv.get("license")),
        original_prompt=old_adv.get("original_prompt") or old_adv.get("context"),
        image_url=old_adv.get("image_url"),
        strict_rules=old_adv.get("strict_rules", True),
        rule_enforcement_mode=old_adv.get("rule_enforcement_mode")
        or data.get("rule_enforcement_mode")
        or "rpg",
        time_per_turn=old_adv.get("time_per_turn", 10),
        pacing_minutes=old_adv.get("pacing_minutes", 5),
        max_time_per_turn=old_adv.get("max_time_per_turn"),
        max_memory_turns=old_adv.get("max_memory_turns") or 10,
        clock_enabled=old_adv.get("clock_enabled", False),
        game_over_rules=old_adv.get("game_over_rules"),
        quests=old_adv.get("quests", []),
        awards=old_adv.get("awards", []),
        original_manifest=old_adv.get("original_manifest"),
        plot=old_adv.get("plot"),
        rules=old_adv.get("rules"),
        intro_text=old_adv.get("intro_text"),
        walkthrough=old_adv.get("walkthrough"),
        completed_condition=old_adv.get("completed_condition"),
        gameover_condition=old_adv.get("gameover_condition"),
        tts_director_notes=old_adv.get("tts_director_notes"),
        starting_timestamp=old_adv.get("starting_timestamp", 0),
        time_system=old_adv.get("time_system", "calendar"),
        time_config=old_adv.get("time_config"),
        allow_dynamic_items=old_adv.get("allow_dynamic_items", False),
        can_damage_npcs=old_adv.get("can_damage_npcs", True),
        npcs_can_damage_protagonist=old_adv.get("npcs_can_damage_protagonist", True),
        cover_source_adventure_id=old_adv.get("cover_source_adventure_id"),
        cover_source_adventure_name=old_adv.get("cover_source_adventure_name"),
        cover_similarity_percent=old_adv.get("cover_similarity_percent", 50),
        allow_reuse_source_assets=old_adv.get("allow_reuse_source_assets", True),
        min_scenes=old_adv.get("min_scenes")
        if old_adv.get("min_scenes") is not None
        else data.get("min_scenes"),
        max_scenes=old_adv.get("max_scenes")
        if old_adv.get("max_scenes") is not None
        else data.get("max_scenes"),
        min_items=old_adv.get("min_items")
        if old_adv.get("min_items") is not None
        else data.get("min_items"),
        max_items=old_adv.get("max_items")
        if old_adv.get("max_items") is not None
        else data.get("max_items"),
        container_generation_enabled=old_adv.get("container_generation_enabled", True)
        if "container_generation_enabled" in old_adv
        else data.get("container_generation_enabled", True),
        scripts_generation_enabled=old_adv.get("scripts_generation_enabled", False)
        if "scripts_generation_enabled" in old_adv
        else data.get("scripts_generation_enabled", False),
        min_containers=old_adv.get("min_containers")
        if old_adv.get("min_containers") is not None
        else data.get("min_containers"),
        max_containers=old_adv.get("max_containers")
        if old_adv.get("max_containers") is not None
        else data.get("max_containers"),
        text_log_generation_enabled=old_adv.get("text_log_generation_enabled", True)
        if "text_log_generation_enabled" in old_adv
        else data.get("text_log_generation_enabled", True),
        min_text_logs=old_adv.get("min_text_logs")
        if old_adv.get("min_text_logs") is not None
        else data.get("min_text_logs"),
        max_text_logs=old_adv.get("max_text_logs")
        if old_adv.get("max_text_logs") is not None
        else data.get("max_text_logs"),
        min_quests=old_adv.get("min_quests")
        if old_adv.get("min_quests") is not None
        else data.get("min_quests"),
        max_quests=old_adv.get("max_quests")
        if old_adv.get("max_quests") is not None
        else data.get("max_quests"),
        quest_generation_enabled=old_adv.get("quest_generation_enabled", True)
        if "quest_generation_enabled" in old_adv
        else data.get("quest_generation_enabled", True),
        min_awards=old_adv.get("min_awards")
        if old_adv.get("min_awards") is not None
        else data.get("min_awards"),
        max_awards=old_adv.get("max_awards")
        if old_adv.get("max_awards") is not None
        else data.get("max_awards"),
        award_generation_enabled=old_adv.get("award_generation_enabled", False)
        if "award_generation_enabled" in old_adv
        else data.get("award_generation_enabled", False),
        language=old_adv.get("language") or data.get("language"),
        origin_id=origin_id,
        is_adventure_generator=old_adv.get("is_adventure_generator", False),
        is_ready=True,
        creation_status="Ready",
    )
