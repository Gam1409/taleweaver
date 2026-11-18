"""Controlled gift sources keep the existing actual-player operation boundary."""

import pytest

from backend.engine import turn_controls
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.npc_actions.control import CommandRejectedError
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_player_item_operations import apply_player
from tests.test_wardrobe_gift_authority import gift_context


async def configured(db, *, performer=PLAYER, basis="performed", creation_ref=0):
    manager, event = await gift_context(db, "player_action", authored=True)
    kernel = KernelState(
        settings=Settings(
            mode="live", workflow="integrated", action_tools=True, actor_ids=["LINA"], agent_steps=1
        )
    )
    manager.state.entity_states = {**manager.state.entity_states, KEY: kernel.model_dump()}
    request = await db.get(ChatMessage, manager._vn_player_message_id)
    raw = {
        "garment_creations": [event._vn_clothing_plan.creations[0].model_dump()],
        "player_item_actions": [
            {
                "operation": "acquire_garment",
                "performer_id": performer,
                "target_id": PLAYER,
                "creation_ref": creation_ref,
                "passage_id": "player:p0",
                "basis": basis,
            }
        ],
    }
    return manager, request, raw


async def test_actual_linked_player_self_acquisition_keeps_its_existing_owner_path():
    async with TestSessionLocal() as db:
        manager, request, raw = await configured(db)
        event, plan = await apply_player(manager, request, raw)
        assert plan.error is None and len(plan.actions) == 1
        created = [row for row in manager.avatar.inventory if row["name"] == "Red scarf"]
        assert len(created) == 1
        source = next(
            row["source"]
            for row in manager.avatar.visual_profile["worn"]
            if row["item_id"] == created[0]["id"]
        )
        assert source["source_role"] == "user" and source["source_message_id"] == request.id
        assert len(event._vn_clothing_plan.creations) == 1


@pytest.mark.parametrize(
    "changes", [{"performer": "LINA"}, {"basis": "attempt"}, {"creation_ref": 1}]
)
async def test_deferred_or_invalid_player_plan_cannot_approve_controlled_giving(changes):
    async with TestSessionLocal() as db:
        manager, request, raw = await configured(db, **changes)
        event, plan = await apply_player(manager, request, raw)
        assert plan.error is not None or plan.actions == ()
        assert not event._vn_clothing_plan.creations
        assert not any(row["name"] == "Red scarf" for row in manager.avatar.inventory)


async def test_old_linked_player_plan_stays_subject_to_its_original_attempt_fence():
    async with TestSessionLocal() as db:
        manager, request, raw = await configured(db)

        def changed_attempt(_event):
            turn_controls.begin(manager)
            turn_controls.bind_input(manager, request)

        with pytest.raises(CommandRejectedError):
            await apply_player(manager, request, raw, mutate=changed_attempt)
        assert not any(row["name"] == "Red scarf" for row in manager.avatar.inventory)
