"""Deferred proposals and stale player plans cannot bypass canonical custody owners."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine import turn_controls
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.control import CommandRejectedError
from backend.engine.visual_novel import player_items
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot
from backend.engine.visual_novel.intent import progression_schema
from tests.conftest import TestSessionLocal
from tests.test_npc_prepass_placements import setup
from tests.test_vn_player_item_operations import action, apply_player


@pytest.mark.parametrize(
    "field", ["new_inventory_items", "spawned_items", "deleted_entities", "updated_entities"]
)
async def test_raw_possession_fields_defer_without_publishing_an_npc_choice(field):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db)
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        ring = deepcopy(before.items["HIDDEN_RING"])
        raw = {field: [ring]}
        if field == "deleted_entities":
            raw[field] = ["HIDDEN_RING"]
        if field == "updated_entities":
            raw[field] = [{"entity_id": "LINA", "inventory": [before.items["BRASS_KEY"]]}]
        event, plan = await apply_player(manager, request, raw)
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners == before.owners and after.items == before.items
        receipt = player_items.outcome(event)
        assert len(receipt) == 1 and receipt[0]["status"] == "deferred"
        assert receipt[0]["parent_operation_id"] == plan.operation.operation_id
        assert receipt[0]["reason_code"] == "preliminary_item_deferred"
        assert "not applied" not in event.narrative_description


async def test_removal_and_implicit_recipient_update_cannot_bypass_player_operations():
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db)
        manager.avatar.inventory = [{"id": key.id, "name": key.name}]
        key.is_in_inventory = True
        await db.commit()
        event, _ = await apply_player(
            manager,
            request,
            {
                "removed_inventory_item_ids": [key.id],
                "updated_entities": [
                    {"entity_id": "LINA", "inventory": [{"id": key.id, "name": key.name}]}
                ],
            },
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners[key.id] == PLAYER
        assert all(row["status"] == "deferred" for row in player_items.outcome(event))


async def test_changed_custody_is_rejected_before_the_player_owner_applies_a_plan():
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text="I take the brass key.")

        def move_to_another_owner(_event):
            states = deepcopy(manager.state.entity_states)
            states["LINA"] = {
                **states.get("LINA", {}),
                "inventory": [
                    {"id": "HIDDEN_RING", "name": "Hidden ring"},
                    {"id": key.id, "name": key.name},
                ],
            }
            states[key.id] = {"is_in_inventory": True}
            manager.state.entity_states = states

        with pytest.raises(CommandRejectedError):
            await apply_player(
                manager,
                request,
                {"player_item_actions": [action("take")]},
                mutate=move_to_another_owner,
            )
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners[key.id] == "LINA"
        assert key.id not in {row["id"] for row in manager.avatar.inventory}


async def test_new_attempt_with_identical_saved_input_cannot_publish_an_old_player_plan():
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text="I take the brass key.")

        def retry(_event):
            turn_controls.begin(manager)
            turn_controls.bind_input(manager, request)

        with pytest.raises(CommandRejectedError):
            await apply_player(
                manager, request, {"player_item_actions": [action("take")]}, mutate=retry
            )
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners[key.id] == SCENE


async def test_new_item_image_does_not_invalidate_a_legal_current_operation():
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text="I take the brass key.")

        def update_image(_event):
            key.image_url = "/data/current-key-image.png"

        event, _ = await apply_player(
            manager, request, {"player_item_actions": [action("take")]}, mutate=update_image
        )
        assert player_items.outcome(event)[0]["status"] == "applied"
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners[key.id] == PLAYER


async def test_partial_guardrail_filtering_reports_each_actual_final_custody():
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I take the key and the ring.")

        def keep_ring_only(event):
            event.new_inventory_items = [
                item for item in event.new_inventory_items if item.id == "HIDDEN_RING"
            ]

        event, _ = await apply_player(
            manager,
            request,
            {"player_item_actions": [action("take"), action("take", item_id="HIDDEN_RING")]},
            mutate=keep_ring_only,
        )
        records = {row["item_id"]: row for row in player_items.outcome(event)}
        assert records["BRASS_KEY"]["status"] == "blocked"
        assert records["HIDDEN_RING"]["status"] == "applied"
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners["BRASS_KEY"] == SCENE and current.owners["HIDDEN_RING"] == PLAYER
        assert len({row["operation_id"] for row in records.values()}) == 2


@pytest.mark.parametrize("changes", [{"action_tools": False}, {"mode": "shadow"}, {"mode": "off"}])
async def test_ordinary_progression_retains_its_existing_owner_when_action_control_is_disabled(
    changes,
):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I take the brass key.", settings=changes)
        event, plan = await apply_player(
            manager, request, {"new_inventory_items": [{"id": "BRASS_KEY", "name": "Brass key"}]}
        )
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners["BRASS_KEY"] == PLAYER
        assert plan is None and player_items.outcome(event) == []


def test_limits_and_selector_types_are_enforced_before_any_player_operation():
    from types import SimpleNamespace

    from backend.engine.chpm.schema import KernelState, Settings
    from backend.engine.chpm.state import KEY

    settings = Settings(
        mode="live", workflow="integrated", action_tools=True, agent_steps=1, actor_ids=["LINA"]
    )
    state = SimpleNamespace(entity_states={KEY: KernelState(settings=settings).model_dump()})
    with pytest.raises(ValidationError):
        progression_schema(state).model_validate(
            {"player_item_actions": [action("take")] * (player_items.MAX_ACTIONS + 1)}
        )
    with pytest.raises(ValidationError):
        player_items.PlayerItemAction(
            performer_id=PLAYER,
            operation="acquire_garment",
            creation_ref=True,
            passage_id="player:p0",
            basis="performed",
            target_id="LINA",
        )
