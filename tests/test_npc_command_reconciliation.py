"""Narrated consequences keep independent state without reversing command-owned effects."""

from types import SimpleNamespace

from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.npc_actions.reconciliation import protect
from tests.npc_control_support import bind_turn
from tests.test_item_command_state import change
from tests.test_npc_action_previews import fixture


def manager(outcomes=None):
    host, scope, _ = fixture()
    host._vn_player_message_id = scope.input_id
    host._chpm_turn = SimpleNamespace(
        input_id=scope.input_id,
        initial=SimpleNamespace(settings=SimpleNamespace(mode="live", action_tools=True)),
        decisions={"npc": None},
        action_outcomes=outcomes or {},
        simplified=False,
    )
    bind_turn(host, host._chpm_turn)
    return host


def action(item, source, destination):
    return {
        "item_id": item,
        "source_owner": source,
        "destination_owner": destination,
        "disposition": "carried",
        "basis": "completed",
        "evidence": "The actor hands over the object.",
    }


def test_applied_transfer_echo_is_not_executed_again_and_original_indices_are_retained():
    host = manager(
        {
            "npc": [
                {
                    "status": "applied",
                    "effect": {
                        "item_id": "KEY",
                        "source_owner": "npc",
                        "destination_owner": "other",
                    },
                }
            ]
        }
    )
    original = ItemExtraction(
        actions=[action("KEY", "npc", "other"), action("OTHER", "other", "__player__")]
    )
    result, indices, errors = protect(host, original, (2, 5))
    assert not errors and indices == (5,)
    assert [row.item_id for row in result.actions] == ["OTHER"]
    assert len(original.actions) == 2


def test_an_unapproved_inventory_change_is_blocked_without_dropping_an_injury():
    host = manager()
    injury = {
        "operation": "record",
        "target_id": "npc",
        "kind": "injury",
        "part": "arm",
        "detail": "A small cut.",
        "evidence": "There is a small cut on the arm.",
    }
    original = ItemExtraction(actions=[action("KEY", "npc", "other")], condition_updates=[injury])
    result, _, errors = protect(host, original)
    assert not result.actions and errors
    assert result.condition_updates == [injury]


def test_only_the_handled_item_dimension_is_protected_and_the_old_value_cannot_return():
    host = manager(
        {"npc": [{"status": "applied", "effect": {"item_id": "COAT", "dimension": "damage"}}]}
    )
    host.state.entity_states, condition_id = change(host.state.entity_states)
    existing = {
        "operation": "change",
        "condition_id": condition_id,
        "detail": "Completely intact.",
        "evidence": "The cuff is completely intact.",
    }
    independent = {
        "operation": "record",
        "target_id": "COAT",
        "kind": "item_state",
        "part": "cleanliness",
        "detail": "Dusty fabric.",
        "evidence": "The fabric is dusty.",
    }
    result, _, errors = protect(host, ItemExtraction(condition_updates=[existing, independent]))
    assert errors and result.condition_updates == [independent]
    echo = {**existing, "detail": "The cuff is torn."}
    result, _, errors = protect(host, ItemExtraction(condition_updates=[echo]))
    assert not errors and not result.condition_updates


def test_a_different_actors_route_receipt_cannot_validate_an_unapproved_departure():
    host = manager({"other": [{"status": "applied", "effect": {"destination_scene_id": "PORCH"}}]})
    movement = {
        "actor_id": "npc",
        "destination_scene_id": "PORCH",
        "basis": "completed",
        "evidence": "The actor goes outside.",
    }
    result, _, errors = protect(host, ItemExtraction(movements=[movement]))
    assert errors and not result.movements


def test_malformed_condition_identifiers_do_not_hide_an_independent_valid_update():
    host = manager(
        {"npc": [{"status": "applied", "effect": {"item_id": "COAT", "dimension": "damage"}}]}
    )
    host.state.entity_states, _ = change(host.state.entity_states)
    malformed = {"operation": "change", "condition_id": {"bad": "value"}}
    result, _, errors = protect(host, ItemExtraction(condition_updates=[malformed]))
    assert result.condition_updates == [malformed] and not errors
