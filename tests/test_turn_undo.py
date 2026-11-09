"""Debug removal rewinds the last whole turn instead of leaving its consequences."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.gameplay.agent_logic import AgentService
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.scene_staging.provenance import stamp
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, project, reconcile
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_turn_replay import seed

GAME = "session-1"
PATH = f"/api/adventures/sessions/{GAME}/messages"
COAT = {
    "id": "COAT",
    "name": "Blue coat",
    "description": "A blue wool coat.",
    "clothing": {"layer": 2, "coverage": ["torso", "arms"], "opaque": True, "underwear": False},
}
PROFILE = {"appearance": {"age_years": 32}, "worn": [{"item_id": "COAT"}]}


async def changed_cycle(manager, _message, auto_visualize=False, language=None):
    actor = await manager.db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == GAME, WorldEntity.id == "NPC")
    )
    manager.avatar.hp -= 10
    manager.avatar.inventory = [deepcopy(COAT)]
    actor.inventory = []
    actor.visual_profile = {"appearance": {"age_years": 32}, "worn": []}
    actor.current_scene_id = "GARDEN"
    manager.state.current_scene_id = "GARDEN"
    manager.state.in_game_time += 15
    manager.state.entity_states = {
        **manager.state.entity_states,
        KEY: {"scene_id": "GARDEN", "status": "ready", "actors": {}},
    }
    await manager._save_chat_message(
        "assistant", "Mira hands over the blue coat. They enter the garden."
    )
    await manager.db.commit()
    yield 'event: final\ndata: {"status":"success"}\n\n'


async def completed_turn(db, monkeypatch):
    _user, avatar, state = await seed(db)
    user = await db.scalar(select(User).where(User.username == "test_user"))
    game = await db.get(GameSession, GAME)
    game.user_id = avatar.user_id = state.user_id = user.id
    state.is_debug_enabled = True
    actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "NPC"))
    actor.character, actor.goal = (
        "Patient, observant and independent.",
        "Find the missing notebook.",
    )
    actor.inventory, actor.visual_profile = [deepcopy(COAT)], deepcopy(PROFILE)
    db.add(WorldScene(id="GARDEN", session_id=GAME, label="Garden", description="An open garden."))
    opening = ChatMessage(session_id=GAME, role="assistant", content="Mira stands by the desk.")
    db.add(opening)
    await db.flush()
    write_settings(state, VnSettings(scene_staging=True))
    cast = [{"id": "av-1"}, {"id": "NPC"}]
    state.entity_states = {
        **state.entity_states,
        KEY: reconcile(
            state,
            cast,
            opening.content,
            SceneExtraction(
                changes=[{"entity_id": "NPC", "posture": "standing", "evidence": opening.content}]
            ),
        ),
    }
    stamp(state, opening)
    await db.commit()
    before = {
        "hp": avatar.hp,
        "inventory": deepcopy(avatar.inventory),
        "scene": state.current_scene_id,
        "minute": state.in_game_time,
        "character": actor.character,
        "goal": actor.goal,
        "opening": opening.id,
    }
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", changed_cycle)
    manager = GameTurnManager(db, GAME, user)
    events = [chunk async for chunk in manager.process_turn("Let us go to the garden.")]
    assert any(chunk.startswith("event: final") for chunk in events), events
    reply = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.session_id == GAME, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert manager.state.current_scene_id == "GARDEN"
    assert manager.avatar.hp == before["hp"] - 10
    return reply.id, before


async def test_debug_removal_undoes_the_complete_latest_turn(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        reply_id, before = await completed_turn(db, monkeypatch)
    response = await auth_client.delete(f"{PATH}/{reply_id}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "undone"
    assert response.json()["deleted_messages"] >= 2
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == GAME))
        avatar = await db.get(Avatar, "av-1")
        actor = await db.scalar(
            select(WorldEntity).where(WorldEntity.id == "NPC", WorldEntity.session_id == GAME)
        )
        assert (state.current_scene_id, state.in_game_time) == (before["scene"], before["minute"])
        assert (avatar.hp, avatar.inventory) == (before["hp"], before["inventory"])
        assert actor.inventory == [COAT] and actor.visual_profile == PROFILE
        assert (actor.character, actor.goal, actor.current_scene_id) == (
            before["character"],
            before["goal"],
            "START",
        )
        assert project(state, [{"id": "av-1"}, {"id": "NPC"}])["NPC"]["posture"] == "standing"
        assert state.is_debug_enabled
        assert list(
            await db.scalars(select(ChatMessage.id).where(ChatMessage.session_id == GAME))
        ) == [before["opening"]]
        assert await db.get(TurnReplay, GAME) is None


async def test_an_older_reply_requires_a_checkpoint_and_is_not_deleted(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        _reply_id, before = await completed_turn(db, monkeypatch)
    response = await auth_client.delete(f"{PATH}/{before['opening']}")
    assert response.status_code == 409
    assert "checkpoint" in response.text.lower()
    async with TestSessionLocal() as db:
        assert await db.get(ChatMessage, before["opening"]) is not None
        state = await db.scalar(select(SessionState).where(SessionState.session_id == GAME))
        assert state.current_scene_id == "GARDEN"


async def test_undo_refuses_an_active_session_writer(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        reply_id, _before = await completed_turn(db, monkeypatch)
    with session_write_lease(GAME):
        response = await auth_client.delete(f"{PATH}/{reply_id}")
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        assert await db.get(ChatMessage, reply_id) is not None


async def test_undo_does_not_restart_a_paused_play_agent(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        reply_id, _before = await completed_turn(db, monkeypatch)
        row = await db.get(TurnReplay, GAME)
        snapshot = deepcopy(row.before)
        snapshot["state"]["entity_states"]["__agent__"] = {"active": True}
        row.before = snapshot
        await db.commit()
    response = await auth_client.delete(f"{PATH}/{reply_id}")
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == GAME))
        assert AgentService.get_agent_state(state)["active"] is False


@pytest.mark.parametrize("damage", ["foreign_owner", "foreign_avatar", "partial_tables"])
async def test_invalid_snapshot_rolls_back_all_changes(auth_client, monkeypatch, damage):
    async with TestSessionLocal() as db:
        reply_id, _before = await completed_turn(db, monkeypatch)
        row = await db.get(TurnReplay, GAME)
        snapshot = deepcopy(row.before)
        if damage == "foreign_owner":
            snapshot["user_id"] = "someone-else"
        elif damage == "foreign_avatar":
            snapshot["avatar"]["id"] = "someone-else-avatar"
        else:
            # restore() has already deleted later messages when this fails.
            snapshot["tables"].pop("world_scenes")
        row.before = snapshot
        await db.commit()
    response = await auth_client.delete(f"{PATH}/{reply_id}")
    assert response.status_code == 409, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == GAME))
        assert state.current_scene_id == "GARDEN"
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "NPC"))
        assert actor.inventory == [] and actor.current_scene_id == "GARDEN"
        assert await db.get(ChatMessage, reply_id) is not None
        assert await db.get(TurnReplay, GAME) is not None
