"""Behavior boundaries retained by the focused gameplay engine refactor."""

from types import SimpleNamespace

import pytest

from backend.engine.hard_rule_evaluator import HardRuleEvaluator
from backend.engine.item_logic import get_item_slot
from backend.engine.quest_manager import QuestManager
from backend.engine.rule_engine import GameEvent, GameOverException, InventoryItem, RuleEngine
from backend.engine.stat_aggregator import calculate_total_stats
from backend.engine.trigger_state import apply_trigger_changes
from backend.models.session_state import SessionState


def test_inventory_mutations_keep_first_match_and_update_remove_add_order():
    avatar = SimpleNamespace(
        name="Hero",
        hp=10,
        stamina=10,
        mana=10,
        status_effects=[],
        inventory=[
            {"id": "A", "name": "First", "custom": "retained"},
            {"id": "A", "name": "Duplicate"},
            {"id": "B", "name": "Removed"},
        ],
    )
    event = GameEvent(
        updated_inventory_items=[InventoryItem(id="A", name="Updated")],
        removed_inventory_item_ids=["B"],
        new_inventory_items=[InventoryItem(id="B", name="Replacement")],
        narrative_description="Complete",
    )
    assert RuleEngine.apply_event(avatar, event) == "Complete"
    assert avatar.inventory == [
        {"id": "A", "name": "Updated", "custom": "retained"},
        {"id": "A", "name": "Duplicate"},
        {"id": "B", "name": "Replacement"},
    ]


def test_death_stops_inventory_changes_before_resource_clamping():
    avatar = SimpleNamespace(name="Hero", hp=1, stamina=1, mana=1, inventory=[])
    event = GameEvent(
        hp_change=-1,
        stamina_change=-5,
        new_inventory_items=[InventoryItem(id="A", name="Never acquired")],
    )
    with pytest.raises(GameOverException):
        RuleEngine.apply_event(avatar, event)
    assert avatar.hp == 0
    assert avatar.stamina == -4
    assert avatar.inventory == []


@pytest.mark.parametrize(
    "name,item_type,slot",
    [
        ("Armguard helmet", "WEARABLE", "Hands"),
        ("Helmet armor", "WEARABLE", "Head"),
        ("Ring amulet", "WEARABLE", "Ring_1"),
        ("Shield", "WEAPON", "MainHand"),
        ("Shield", "TOOL", "OffHand"),
        ("Hammer", "TOOL", "MainHand"),
        ("Plain object", "WEARABLE", None),
    ],
)
def test_item_slot_keeps_keyword_and_type_precedence(name, item_type, slot):
    assert get_item_slot(name, item_type) == slot


def test_hard_item_rules_keep_legacy_representation_identity():
    state = SimpleNamespace(entity_states={"STATE_ITEM": {"is_in_inventory": True}})
    avatar = SimpleNamespace(inventory=[SimpleNamespace(id="OBJECT_ID", name="Object name")])
    assert HardRuleEvaluator.check_item_rule("object_id", avatar, state)
    # Objects historically prefer their ID, while dictionaries expose both ID and name.
    assert not HardRuleEvaluator.check_item_rule("Object name", avatar, state)
    assert HardRuleEvaluator.check_item_rule(
        "dict name", avatar, state, [{"id": "D", "name": "Dict name"}]
    )
    assert HardRuleEvaluator.check_item_rule("state_item", avatar, state)


def test_unsatisfied_hard_quest_never_falls_back_to_equipped_goal():
    avatar = SimpleNamespace(equipment={"Head": {"id": "HAT"}}, inventory=[])
    state = SimpleNamespace(
        quests=[
            {"id": "Q", "goal": "Equip head", "required_item_id": "MISSING"},
            {"id": "SOFT", "goal": "Equip head"},
        ],
        entity_states={},
    )
    assert QuestManager.evaluate_quests(avatar, state) == ["SOFT"]


def test_stat_overrides_then_legacy_flat_and_status_modifiers_are_cumulative():
    avatar = SimpleNamespace(
        strength=1,
        dexterity=2,
        intelligence=3,
        wisdom=4,
        charisma=5,
        armor_class=6,
        stats={"STR": 10, "luck": 4},
        equipment={
            "Head": {
                "stat_modifiers": {"strength": 3, "luck": 2},
                "stat_modifier_strength": 2,
                "stat_modifier_luck": 1,
            }
        },
        status_effects=["Weakened"],
    )
    stats = calculate_total_stats(avatar)
    assert stats["strength"] == 13
    assert stats["luck"] == 7
    assert stats["armor_class"] == 6


def test_trigger_changes_preserve_unrelated_state_and_merge_repeated_entities():
    state = SessionState(
        entity_states={"__script_vars__": {"old": 1}, "NPC": {"hp": 10, "name": "Mira"}},
        exit_states={"A:B": {"is_locked": True, "lock_description": "Old", "note": "Keep"}},
    )
    changes = SimpleNamespace(
        var_updates={"new": 2},
        entity_updates=[{"entity_id": "NPC", "hp": 5}, {"entity_id": "NPC", "mood": "calm"}],
        exit_updates=[{"from_scene_id": "A", "to_scene_id": "B", "is_locked": False}],
    )
    apply_trigger_changes(state, changes)
    assert state.entity_states == {
        "__script_vars__": {"old": 1, "new": 2},
        "NPC": {"hp": 5, "name": "Mira", "mood": "calm"},
    }
    assert state.exit_states["A:B"] == {
        "is_locked": False,
        "lock_description": "Old",
        "note": "Keep",
    }
