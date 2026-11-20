"""Player proposals use saved references; only the canonical owner publishes custody."""

import json
from copy import deepcopy

import pytest

from backend.engine import turn_controls
from backend.engine.clothing.planning import prepare_wardrobe_plan
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.turn_prompt_layout import build_outcome_json
from backend.engine.mutation_targets import validate_mutation_targets
from backend.engine.npc_actions.control import CommandRejectedError
from backend.engine.visual_novel import player_items
from backend.engine.visual_novel.continuity import (
    PLAYER,
    SCENE,
    possession_snapshot,
    prepare_intent,
)
from backend.engine.visual_novel.intent import progression_schema
from backend.engine.visual_novel.movement_recovery import resolve_event
from tests.conftest import TestSessionLocal
from tests.test_clothing_runtime import item, profile
from tests.test_npc_prepass_placements import setup


def action(operation, *, item_id="BRASS_KEY", **fields):
    return {
        "operation": operation,
        "performer_id": PLAYER,
        "item_id": item_id,
        "passage_id": "player:p0",
        "basis": "performed",
        **fields,
    }


async def apply_player(manager, request, raw, *, mutate=None):
    """Use the real progression/application boundary without running inference."""
    rows = await session_objects(manager.db, manager.game_id)
    turn_controls.bind_input(manager, request)
    captured = turn_controls.scope(manager, "preliminary_items")
    proposal = progression_schema(manager.state).model_validate(raw)
    manager._vn_movement_proposal = proposal.model_copy(deep=True)
    plan = await player_items.prepare(
        manager, proposal, rows, scope=player_items.capture(manager), captured=captured
    )
    intent = prepare_intent(manager, proposal, rows, control=captured, item_plan=plan)
    event = manager._build_progression_event(intent)
    player_items.attach(event, plan)
    await prepare_wardrobe_plan(manager, event, proposal, request.content, rows, [])
    await validate_mutation_targets(manager, event)
    await resolve_event(manager, event)
    if mutate is not None:
        mutate(event)
    await manager._apply_game_event(event)
    await manager.db.commit()
    return event, plan


@pytest.mark.parametrize(
    "operations,start_carried,expected",
    [
        ([action("take")], False, PLAYER),
        ([action("take"), action("give", target_id="LINA")], False, "LINA"),
        ([action("drop")], True, SCENE),
        ([action("consume")], True, None),
        ([action("destroy")], False, None),
        ([action("take", item_id="HIDDEN_RING")], False, PLAYER),
    ],
)
async def test_completed_player_operations_apply_once_with_canonical_identity(
    operations, start_carried, expected
):
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text="I complete the described item action.")
        if start_carried:
            manager.avatar.inventory = [{"id": key.id, "name": key.name}]
            key.is_in_inventory = True
            await db.commit()
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        identifier = operations[-1]["item_id"]
        event, plan = await apply_player(manager, request, {"player_item_actions": operations})
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners.get(identifier) == expected
        assert {k: v for k, v in after.owners.items() if k != identifier} == {
            k: v for k, v in before.owners.items() if k != identifier
        }
        if expected is not None:
            assert after.items[identifier]["name"] == before.items[identifier]["name"]
        receipt = player_items.outcome(event)
        assert len(receipt) == 1 and receipt[0]["status"] == "applied"
        assert receipt[0]["parent_operation_id"] == plan.operation.operation_id
        assert receipt[0]["effect"]["item_id"] == identifier
        _, wire = build_outcome_json(event)
        assert json.loads(wire)["preliminary_player_item_outcomes"] == receipt


@pytest.mark.parametrize(
    "operations",
    [
        [action("give", target_id="LINA"), action("take")],
        [action("take", item_id="UNKNOWN")],
        [action("take", item_id="BRASS_KEY ")],
        [action("take", passage_id="player:p0 ")],
        [action("take", passage_id="player:p99")],
    ],
)
async def test_invalid_player_plan_preserves_all_existing_possessions(operations):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db)
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        _, plan = await apply_player(manager, request, {"player_item_actions": operations})
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert plan.error is not None
        assert after.owners == before.owners and after.items == before.items


async def test_filtered_player_transfer_is_not_reported_as_applied():
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I take the brass key.")

        def block(event):
            event.new_inventory_items = []
            event.updated_entities = []

        event, _ = await apply_player(
            manager, request, {"player_item_actions": [action("take")]}, mutate=block
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners["BRASS_KEY"] == SCENE
        assert player_items.outcome(event)[0]["status"] == "blocked"


async def test_late_old_player_proposal_cannot_be_rebound_after_source_await(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I take the brass key.")
        turn_controls.bind_input(manager, request)
        captured = turn_controls.scope(manager, "preliminary_items")
        original = player_items.resolve

        async def replace_attempt(*args):
            result = await original(*args)
            turn_controls.begin(manager)
            turn_controls.bind_input(manager, request)
            return result

        monkeypatch.setattr(player_items, "resolve", replace_attempt)
        proposal = progression_schema(manager.state).model_validate(
            {"player_item_actions": [action("take")]}
        )
        with pytest.raises(CommandRejectedError):
            await player_items.prepare(
                manager,
                proposal,
                await session_objects(db, manager.game_id),
                scope=player_items.capture(manager),
                captured=captured,
            )
        assert "BRASS_KEY" not in {row["id"] for row in manager.avatar.inventory}


@pytest.mark.parametrize(
    "agency,authorized",
    [("npc_choice", False), ("consented_assistance", False), ("consented_assistance", True)],
)
async def test_fresh_wardrobe_change_requires_its_correct_action_owner(agency, authorized):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I help Lina put on her coat.")
        npc = next(row for row in await session_objects(db, manager.game_id) if row.id == "LINA")
        npc.inventory = [*deepcopy(npc.inventory), item()]
        npc.visual_profile = profile()
        await db.commit()
        change = {
            "actor_id": "LINA",
            "source": "player_action",
            "evidence": request.content,
            "basis": "performed",
            "agency": agency,
            "npc_decision": "approved",
            "reason": "The current player action helps with the existing coat.",
            "item_id": "coat",
            "operation": "wear",
        }
        raw = {"wardrobe_actions": [change]}
        if authorized:
            raw["player_item_actions"] = [action("wear", item_id="coat", target_id="LINA")]
        await apply_player(manager, request, raw)
        current = manager.state.entity_states.get("LINA", {}).get(
            "visual_profile", npc.visual_profile
        )
        assert ("coat" in {entry["item_id"] for entry in current["worn"]}) is authorized
        assert {
            row["id"]
            for row in manager.state.entity_states.get("LINA", {}).get("inventory", npc.inventory)
        } == {"coat", "HIDDEN_RING"}


def test_player_operation_schema_is_bounded_and_disabled_modes_keep_legacy_contract():
    from types import SimpleNamespace

    from backend.engine.chpm.schema import KernelState, Settings
    from backend.engine.chpm.state import KEY
    from backend.engine.visual_novel.intent import progression_prompt

    active = Settings(
        mode="live", workflow="integrated", action_tools=True, agent_steps=1, actor_ids=["LINA"]
    )
    state = SimpleNamespace(entity_states={KEY: KernelState(settings=active).model_dump()})
    assert (
        progression_schema(state).model_json_schema()["properties"]["player_item_actions"][
            "maxItems"
        ]
        == player_items.MAX_ACTIONS
    )
    assert "Use player_item_actions" in progression_prompt(state)
    assert "adjudicate their independent" not in progression_prompt(state)
    assert "An NPC transfer must also update" not in progression_prompt(state)
    for changes in (
        {"mode": "off"},
        {"mode": "shadow"},
        {"workflow": "staged", "action_tools": False},
        {"action_tools": False},
    ):
        settings = active.model_copy(update=changes)
        state.entity_states = {KEY: KernelState(settings=settings).model_dump()}
        assert "player_item_actions" not in progression_schema(state).model_fields
        assert "An NPC transfer must also update" in progression_prompt(state)
