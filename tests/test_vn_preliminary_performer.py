"""Preliminary item proposals identify their performer without granting NPC authority."""

import pytest
from pydantic import ValidationError

from backend.engine.clothing.visuals import session_objects
from backend.engine.visual_novel import player_items
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot
from tests.conftest import TestSessionLocal
from tests.test_npc_prepass_placements import setup
from tests.test_vn_player_item_operations import action, apply_player


def test_missing_performer_never_defaults_to_a_completed_player_action():
    raw = action("take")
    raw.pop("performer_id", None)
    with pytest.raises(ValidationError, match="performer_id"):
        player_items.PlayerItemAction.model_validate(raw)


@pytest.mark.parametrize("performer", ["LINA", None])
async def test_other_or_unresolved_performer_preserves_custody_and_reports_deferral(performer):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="Lina, take the brass key and give it to me.")
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        event, plan = await apply_player(
            manager,
            request,
            {"player_item_actions": [action("take", performer_id=performer)]},
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert plan.error is None and plan.actions == ()
        assert after.owners == before.owners and after.items == before.items
        assert after.owners["BRASS_KEY"] == SCENE
        receipt = player_items.outcome(event)
        assert len(receipt) == 1 and receipt[0]["status"] == "deferred"
        assert receipt[0]["item_ids"] == ["BRASS_KEY"]
        assert receipt[0]["parent_operation_id"] == plan.operation.operation_id


async def test_explicit_player_performer_keeps_the_existing_pickup_owner():
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I take the brass key from the table.")
        event, plan = await apply_player(
            manager,
            request,
            {"player_item_actions": [action("take", performer_id=PLAYER)]},
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners["BRASS_KEY"] == PLAYER
        assert len(plan.actions) == 1
        assert player_items.outcome(event)[0]["status"] == "applied"


@pytest.mark.parametrize("performer", ["FOREIGN", "LINA ", "__player__ ", "__scene__"])
async def test_unknown_or_padded_performer_cannot_authorize_or_retarget_a_transfer(performer):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="Lina, take the brass key.")
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        event, plan = await apply_player(
            manager,
            request,
            {"player_item_actions": [action("take", performer_id=performer)]},
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert plan.error is not None
        assert after.owners == before.owners and after.items == before.items
        assert player_items.outcome(event) == []


@pytest.mark.parametrize("basis", ["attempt", "intention", "uncertain"])
async def test_uncompleted_player_proposal_is_deferred_without_an_applied_receipt(basis):
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="I consider taking the brass key.")
        event, _ = await apply_player(
            manager,
            request,
            {"player_item_actions": [action("take", performer_id=PLAYER, basis=basis)]},
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners["BRASS_KEY"] == SCENE
        assert [row["status"] for row in player_items.outcome(event)] == ["deferred"]


async def test_mixed_npc_request_and_player_action_preserve_separate_owner_boundaries():
    async with TestSessionLocal() as db:
        manager, _, request = await setup(db, text="Lina, take the brass key. I take the ring.")
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        event, _ = await apply_player(
            manager,
            request,
            {
                "player_item_actions": [
                    action("take", performer_id="LINA"),
                    action(
                        "take",
                        performer_id=PLAYER,
                        item_id="HIDDEN_RING",
                        passage_id="player:p1",
                    ),
                ]
            },
        )
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners["BRASS_KEY"] == before.owners["BRASS_KEY"] == SCENE
        assert after.owners["HIDDEN_RING"] == PLAYER
        assert {key: value for key, value in after.owners.items() if key != "HIDDEN_RING"} == {
            key: value for key, value in before.owners.items() if key != "HIDDEN_RING"
        }
        outcomes = player_items.outcome(event)
        assert [row["status"] for row in outcomes] == ["deferred", "applied"]
        assert outcomes[0]["item_ids"] == ["BRASS_KEY"]
        assert outcomes[1]["item_id"] == "HIDDEN_RING"
