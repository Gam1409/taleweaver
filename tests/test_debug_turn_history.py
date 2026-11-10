"""Rolling Debug points reuse full checkpoints and cut the discarded future safely."""

from copy import deepcopy

from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_checkpoint_world import SID, checkpoint, restore
from tests.test_item_repair import chpm_world, portrait_world, repair_world
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

__all__ = ["chpm_world", "portrait_world", "repair_world"]
DEBUG_REASON = "DEBUG_TURN"


async def points(db, session_id):
    return list(
        await db.scalars(
            select(SessionCheckpoint)
            .where(SessionCheckpoint.session_id == session_id)
            .order_by(SessionCheckpoint.created_at, SessionCheckpoint.id)
        )
    )


async def test_debug_keeps_exactly_five_pre_turn_states_and_restores_the_oldest(monkeypatch):
    install_roles(monkeypatch, TurnRoles())
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        for turn in range(7):
            state.entity_states = {**state.entity_states, "rollback_probe": {"turn": turn}}
            state.in_game_time = turn * 10
            actor.metadata_json = {"probe": turn}
            await db.commit()
            host = GameTurnManager(db, state.session_id, user)
            events = [event async for event in host.process_turn(f'I say "Continue {turn}".')]
            assert any(event.startswith("event: final") for event in events), "".join(events)
        saved = [
            point
            for point in await points(db, state.session_id)
            if point.trigger_reason == DEBUG_REASON
        ]
        assert len(saved) == 5
        assert [
            point.state_snapshot["session_state"]["entity_states"]["rollback_probe"]["turn"]
            for point in saved
        ] == [2, 3, 4, 5, 6]
        target = saved[0]
        assert target.state_snapshot["debug_turn"]["turn_number"] == 3
        deleted = await SessionCheckpointService.restore_checkpoint(db, state.session_id, target.id)
        await db.commit()
        await db.refresh(state)
        await db.refresh(actor)
        assert deleted >= 10
        assert state.is_debug_enabled and state.in_game_time == 20
        assert state.entity_states["rollback_probe"] == {"turn": 2}
        assert actor.metadata_json == {"probe": 2}
        assert await db.get(TurnReplay, state.session_id) is None
        assert [
            point.id
            for point in await points(db, state.session_id)
            if point.trigger_reason == DEBUG_REASON
        ] == [target.id]
        texts = list(
            await db.scalars(select(ChatMessage.content).where(ChatMessage.role == "user"))
        )
        assert not any(f"Continue {turn}" in text for turn in range(2, 7) for text in texts)


async def test_debug_points_do_not_evict_regular_milestones_or_manual_points():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        manual = await SessionCheckpointService.create_checkpoint(db, state.session_id, "MANUAL")
        for _ in range(5):
            await SessionCheckpointService.create_checkpoint(db, state.session_id, "SCENE_CHANGE")
        for _ in range(7):
            await SessionCheckpointService.create_checkpoint(db, state.session_id, DEBUG_REASON)
        rows = await points(db, state.session_id)
        assert manual in rows
        assert sum(point.trigger_reason == "SCENE_CHANGE" for point in rows) == 5
        assert sum(point.trigger_reason == DEBUG_REASON for point in rows) == 5


async def test_normal_play_does_not_add_debug_points(monkeypatch):
    install_roles(monkeypatch, TurnRoles())
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        host = GameTurnManager(db, state.session_id, user)
        events = [event async for event in host.process_turn("Hello.")]
        assert any(event.startswith("event: final") for event in events)
        assert not any(
            point.trigger_reason == DEBUG_REASON for point in await points(db, state.session_id)
        )


async def test_checkpoint_restore_discards_future_points_and_stale_replay(
    auth_client, repair_world
):
    async with TestSessionLocal() as db:
        first = await checkpoint(db)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        before = deepcopy(state.entity_states)
        db.add(ChatMessage(session_id=SID, role="assistant", content="A future event."))
        await db.commit()
        future = await checkpoint(db)
        db.add(TurnReplay(session_id=SID, before={}, input_text="Future", status="ready"))
        await db.commit()
    await restore(auth_client, first)
    async with TestSessionLocal() as db:
        assert await db.get(SessionCheckpoint, first) is not None
        assert await db.get(SessionCheckpoint, future) is None
        assert await db.get(TurnReplay, SID) is None
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        assert state.entity_states.get("NPC_NEW") == before.get("NPC_NEW")


async def test_checkpoint_restore_cannot_interleave_with_an_active_turn(auth_client, repair_world):
    async with TestSessionLocal() as db:
        target = await checkpoint(db)
    with session_write_lease(SID):
        response = await auth_client.post(
            f"/api/adventures/sessions/{SID}/checkpoints/{target}/restore"
        )
    assert response.status_code == 409
