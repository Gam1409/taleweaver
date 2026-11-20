"""Command authority survives identities normalized by the downstream owners."""

from copy import deepcopy

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.narrated_movement.runtime import Pending, _event
from backend.engine.npc_actions.reconciliation import unpack
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.references import bind_records
from backend.engine.visual_novel.continuity import possession_snapshot
from tests.observable_state_support import world
from tests.test_item_command_state import change
from tests.test_npc_command_reconciliation import manager


@pytest.mark.parametrize(
    "item,source,destination,disposition,narration",
    [
        ("FLASK", "Nora", "Visitor", "carried", "Nora gives the flask to Visitor."),
        ("KEY", "__scene__", "Nora", "carried", "Nora takes the key from the table."),
        ("COAT", "Nora", "Nora", "carried", "Nora takes off the coat and carries it."),
    ],
)
def test_actor_names_cannot_bypass_command_inventory_authority(
    item, source, destination, disposition, narration
):
    host = manager()
    _, rows = world()
    next(row for row in rows if row.id == "npc").name = "Nora"
    next(row for row in rows if row.id == "other").name = "Visitor"
    actors = actor_records(host, rows)
    original = deepcopy(actors)
    injury = {
        "operation": "record",
        "target_id": "npc",
        "kind": "injury",
        "part": "arm",
        "detail": "A small cut.",
        "evidence": "A small cut is visible.",
    }
    extraction = ItemExtraction(
        actions=[
            {
                "item_id": item,
                "source_owner": source,
                "destination_owner": destination,
                "disposition": disposition,
                "basis": "completed",
                "evidence": narration,
            }
        ],
        condition_updates=[injury],
    )
    guarded, failures, denied, indices, errors = unpack(host, extraction, actors)
    changed, accepted, owner_errors = apply_actions(
        guarded,
        actors,
        possession_snapshot(host, rows),
        narration,
        detailed=False,
        session_id="session",
        message_id="input",
        source_indices=indices,
    )
    assert not accepted and changed == original
    assert errors and not failures and not denied and not owner_errors
    assert guarded.condition_updates == [injury]


def test_names_of_uncontrolled_actors_keep_their_existing_transfer_behavior():
    host = manager()
    _, rows = world()
    next(row for row in rows if row.id == "other").name = "Visitor"
    actors = actor_records(host, rows)
    narration = "Visitor gives the small object to the player."
    extraction = ItemExtraction(
        actions=[
            {
                "item_id": "OTHER_BAG_SECRET",
                "source_owner": "Visitor",
                "destination_owner": "__player__",
                "disposition": "carried",
                "basis": "completed",
                "evidence": narration,
            }
        ]
    )
    guarded, failures, denied, indices, errors = unpack(host, extraction, actors)
    _, accepted, owner_errors = apply_actions(
        guarded,
        actors,
        possession_snapshot(host, rows),
        narration,
        detailed=False,
        session_id="session",
        message_id="input",
        source_indices=indices,
    )
    assert len(accepted) == 1 and accepted[0]["source_owner"] == "other"
    assert not failures and not denied and not errors and not owner_errors


@pytest.mark.parametrize("identity", ["condition_id", "echoed_update", "record"])
def test_normalized_condition_identity_cannot_reverse_a_command_property(identity):
    host = manager(
        {"npc": [{"status": "applied", "effect": {"item_id": "COAT", "dimension": "damage"}}]}
    )
    host.state.entity_states, identifier = change(host.state.entity_states)
    update = {
        "operation": "change",
        "condition_id": f" {identifier} ",
        "detail": "Completely intact.",
        "evidence": "Completely intact.",
    }
    if identity == "record":
        update.pop("condition_id")
        update.update(operation="record", target_id=" COAT ", kind="item_state", part=" damage ")
    if identity == "echoed_update":
        update.update(target_id=" COAT ", kind="item_state", part=" damage ")
    injury = {
        "operation": "record",
        "target_id": "npc",
        "kind": "injury",
        "part": "arm",
        "detail": "A small cut.",
        "evidence": "A small cut is visible.",
    }
    guarded, _, _, _, errors = unpack(host, ItemExtraction(condition_updates=[update, injury]), {})
    proposals, _ = bind_records(read(host.state.entity_states), guarded.condition_updates)
    after, accepted, owner_errors = apply(
        host.state.entity_states,
        proposals,
        targets={"COAT", "npc"},
        item_targets={"COAT"},
        narration="Completely intact. A small cut is visible.",
        message_id="reply",
        session_id="session",
        minute=6,
    )
    assert read(after).conditions[identifier].detail == "The cuff is torn."
    assert errors and not owner_errors
    assert len(accepted) == 1 and read(after).conditions[accepted[0]].kind == "injury"
    assert guarded.condition_updates == [injury]


def test_normalized_actor_id_cannot_bypass_command_movement_authority():
    host = manager()
    controlled = {
        "actor_id": " npc ",
        "destination_scene_id": "PORCH",
        "basis": "completed",
        "evidence": "Nora goes outside.",
    }
    independent = {**controlled, "actor_id": "other", "evidence": "Visitor goes outside."}
    guarded, _, _, _, errors = unpack(host, ItemExtraction(movements=[controlled, independent]), {})
    pending = Pending(
        {
            "scene_id": "room",
            "actors": {
                actor: {"can_move": True, "allowed_destinations": ["PORCH"]}
                for actor in ("npc", "other")
            },
        },
        "Nora goes outside. Visitor goes outside.",
        "",
        proposals=guarded.movements,
    )
    _, accepted, owner_errors = _event(pending)
    assert [row["actor_id"] for row in accepted] == ["other"]
    assert errors and not owner_errors


def test_unknown_actor_names_still_reach_the_existing_owner_error():
    host = manager()
    _, rows = world()
    actors = actor_records(host, rows)
    narration = "An unknown visitor picks up the key."
    extraction = ItemExtraction(
        actions=[
            {
                "item_id": "KEY",
                "source_owner": "__scene__",
                "destination_owner": "Unknown visitor",
                "disposition": "carried",
                "basis": "completed",
                "evidence": narration,
            }
        ]
    )
    guarded, _, _, indices, errors = unpack(host, extraction, actors)
    _, accepted, owner_errors = apply_actions(
        guarded,
        actors,
        possession_snapshot(host, rows),
        narration,
        detailed=False,
        session_id="session",
        message_id="input",
        source_indices=indices,
    )
    assert not accepted and owner_errors and not errors


def test_malformed_references_do_not_hide_an_independent_item_dimension():
    host = manager(
        {"npc": [{"status": "applied", "effect": {"item_id": "COAT", "dimension": "damage"}}]}
    )
    host.state.entity_states, identifier = change(host.state.entity_states)
    malformed_condition = {"operation": "change", "condition_id": {"bad": "value"}}
    malformed_movement = {"actor_id": {"bad": "value"}}
    independent = {
        "operation": "record",
        "target_id": "COAT",
        "kind": "item_state",
        "part": "cleanliness",
        "detail": "Dusty fabric.",
        "evidence": "Dusty fabric.",
    }
    guarded, _, _, _, errors = unpack(
        host,
        ItemExtraction(
            condition_updates=[malformed_condition, independent],
            movements=[malformed_movement],
        ),
        {},
    )
    after, accepted, owner_errors = apply(
        host.state.entity_states,
        guarded.condition_updates,
        targets={"COAT"},
        item_targets={"COAT"},
        narration="Dusty fabric.",
        message_id="reply",
        session_id="session",
        minute=6,
    )
    assert guarded.movements == [malformed_movement]
    assert guarded.condition_updates == [malformed_condition, independent] and not errors
    assert owner_errors and len(accepted) == 1
    assert read(after).conditions[accepted[0]].part == "cleanliness"
    assert read(after).conditions[identifier].detail == "The cuff is torn."
