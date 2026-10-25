"""VN continuity retains supported transitions without exposing RPG mutation fields."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routes.adventures.turn_helpers import TurnProgressionBuilder
from backend.engine.dynamic_locations.prompts import intent_schema
from backend.engine.dynamic_locations.schema import KEY
from backend.engine.llm_intents import ChatProgressionIntent
from backend.engine.visual_novel.intent import (
    VNProgressionIntent,
    build_progression_context,
    to_chat_progression_intent,
)


def test_hostile_rpg_fields_are_absent_from_schema_and_ignored_on_conversion():
    payload = {
        "narrative_description": "The conversation continues.",
        "hp_change": -999,
        "stamina_change": -999,
        "mana_change": 999,
        "completed_quest_ids": ["QUEST"],
        "earned_award_keys": ["AWARD"],
        "sequence_completed": True,
        "new_sequence_id": "ENDING",
        "game_over": True,
        "game_completed": True,
        "xp": 10000,
        "new_status_effects": ["Poisoned"],
        "requested_attacks": [{"target_id": "npc"}],
        "updated_entities": [
            {"entity_id": "npc", "notes": "Stands by the door", "hp": 0, "is_defeated": True}
        ],
    }

    intent = to_chat_progression_intent(payload)
    event = TurnProgressionBuilder.build_progression_event(intent)

    forbidden = set(payload) - {"narrative_description", "updated_entities"}
    assert forbidden.isdisjoint(VNProgressionIntent.model_json_schema()["properties"])
    assert event.hp_change == event.stamina_change == event.mana_change == 0
    assert not event.game_over and not event.game_completed and not event.sequence_completed
    assert not event.completed_quest_ids and not event.earned_award_keys
    assert not event.new_status_effects and not event.requested_attacks
    assert event.updated_entities[0].notes == "Stands by the door"
    assert event.updated_entities[0].hp is None and event.updated_entities[0].is_defeated is None


def test_legacy_model_response_is_revalidated_and_supported_fields_survive():
    legacy = ChatProgressionIntent(
        hp_change=-10,
        game_over=True,
        new_scene_id="GARDEN",
        moved_entities=[{"entity_id": "npc", "to_scene_id": "GARDEN"}],
        updated_exits=[{"from_scene_id": "HALL", "to_scene_id": "GARDEN", "is_locked": False}],
        new_inventory_items=[{"id": "key", "name": "Ключ", "hp_change": 999}],
        updated_entities=[{"entity_id": "npc", "inventory": []}],
        discovered_entity_ids=["key"],
        remember_notes=["The key was given to the player."],
        extra_time_minutes=5,
    )

    event = TurnProgressionBuilder.build_progression_event(to_chat_progression_intent(legacy))

    assert event.new_scene_id == "GARDEN" and event.extra_time_minutes == 5
    assert event.moved_entities[0].entity_id == "npc"
    assert event.updated_exits[0].is_locked is False
    assert event.new_inventory_items[0].id == "key"
    assert event.new_inventory_items[0].hp_change is None
    assert event.updated_entities[0].inventory == []
    assert event.discovered_entity_ids == ["key"]
    assert event.remember_notes == ["The key was given to the player."]
    assert event.hp_change == 0 and not event.game_over


def test_dynamic_place_extension_remains_available_until_world_resolution():
    state = SimpleNamespace(entity_states={KEY: {"policy": {"enabled": True}}})
    schema = intent_schema(VNProgressionIntent, state)
    proposal = schema.model_validate(
        {"new_local_place": {"label": "Кафе", "action_quote": "Захожу в кафе"}}
    )
    assert proposal.new_local_place.label == "Кафе"
    proposal.new_scene_id = "dyn_resolved"
    event = TurnProgressionBuilder.build_progression_event(to_chat_progression_intent(proposal))
    assert event.new_scene_id == "dyn_resolved"


@pytest.mark.parametrize("elapsed", [-1, 1441])
def test_unbounded_or_reverse_time_is_rejected(elapsed):
    with pytest.raises(ValidationError):
        VNProgressionIntent.model_validate({"extra_time_minutes": elapsed})


def test_context_is_current_and_does_not_import_quest_or_private_state():
    manager = SimpleNamespace(
        state=SimpleNamespace(current_scene_id="HALL", in_game_time=90, quests=["secret quest"]),
        avatar=SimpleNamespace(
            inventory=[{"id": "key", "name": "Ключ", "stat_modifier_strength": 7}]
        ),
        _get_gm_notes=lambda: ["The player promised to return."],
    )
    scenes = [{"id": "HALL", "label": "Прихожая"}, {"id": "GARDEN", "label": "Сад"}]
    context = build_progression_context(
        manager,
        npcs=[
            {
                "id": "npc",
                "name": "Анна",
                "scene_id": "HALL",
                "private_plan": "A secret",
                "inventory": [{"id": "book", "name": "Книга", "hp_change": 5}],
            },
            {"id": "absent", "name": "Far away", "scene_id": "GARDEN"},
        ],
        scenes=scenes,
        exits=[{"to_scene_id": "GARDEN", "is_locked": True}],
        locked_containers=[{"id": "box", "code_to_unlock": "123"}],
    )
    data = json.loads(context.split("\n", 1)[1])
    assert data["current_location"] == scenes[0]
    assert [npc["id"] for npc in data["present_characters"]] == ["npc"]
    assert data["present_characters"][0]["inventory"] == [{"id": "book", "name": "Книга"}]
    assert data["player_possessions"] == [{"id": "key", "name": "Ключ"}]
    assert data["locked_containers"][0]["code_to_unlock"] == "123"
    assert "secret quest" not in context and "A secret" not in context
