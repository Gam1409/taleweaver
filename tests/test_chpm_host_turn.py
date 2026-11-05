"""Real VN transactions with mocked inference exercise the host/core boundary."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


def roles_for(monkeypatch):
    roles = ChpmRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    return roles


async def configured(db, mode="live"):
    user, _, state, _ = await seed_vn(db)
    state.entity_states = {
        **state.entity_states,
        KEY: KernelState(settings=Settings(mode=mode, actor_ids=["LINA"])).model_dump(),
    }
    await db.commit()
    return user, state


async def run(db, user, text=ACTION):
    manager = GameTurnManager(db, "session-1", user)
    chunks = [chunk async for chunk in manager.process_turn(text)]
    return manager, chunks


async def test_core_is_committed_with_reply_and_original_identity_reaches_both_roles(monkeypatch):
    roles = roles_for(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        manager, chunks = await run(db, user)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        saved = load(manager.state).minds["LINA"]
        assert saved.genesis.identity.description == "Values honesty."
        assert {item.source_kind for item in saved.snapshot.evidence} == {"witnessed", "reported"}
        messages = {row.id: row for row in await db.scalars(select(ChatMessage))}
        assert all(source.message_id in messages for source in saved.sources.values())
        context = roles.proposal_inputs[0]["psychological_state"]
        frame = json.loads(context["current_host_observations"][0]["text"])
        assert frame["scene_id"] == manager.state.current_scene_id
        assert frame["observation"] == "current_host_state"
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LINA"
            )
        )
        npc.character = "NEW_CARD_MUST_NOT_REPLACE_ORIGINAL"
        npc.goal = "NEW_GOAL_MUST_NOT_REPLACE_ORIGINAL"
        await db.commit()
        manager, chunks = await run(db, user, "Я продолжаю разговор.")
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert roles.proposal_inputs[-1]["authored_character"] == "Values honesty."
        assert (
            roles.proposal_inputs[-1]["authored_goal"] == saved.genesis.identity.authored_goals[0]
        )
        assert load(manager.state).minds["LINA"].genesis == saved.genesis
        assert '"authored_identity"' in str(roles.prompts[-1])
        assert load(state).minds["LINA"].snapshot.cursor > saved.snapshot.cursor


async def test_failed_second_turn_and_full_snapshot_restore_preserve_core_exactly(monkeypatch):
    roles = roles_for(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        manager, _ = await run(db, user)
        before = load(manager.state)
        snapshot = await capture(db, "session-1")
        roles.reject = True
        _, chunks = await run(db, user, "Следующий вопрос.")
        assert any(chunk.startswith("event: error") for chunk in chunks)
        assert not any(chunk.startswith("event: chunk") for chunk in chunks)
        await db.refresh(state)
        assert load(state) == before
        roles.reject = False
        _, chunks = await run(db, user, "Второй успешный ход.")
        assert any(chunk.startswith("event: final") for chunk in chunks)
        await restore(db, "session-1", snapshot)
        await db.commit()
        await db.refresh(state)
        assert load(state) == before


async def test_changed_message_drops_core_descendants_before_next_proposal(monkeypatch):
    roles = roles_for(monkeypatch)
    async with TestSessionLocal() as db:
        user, _ = await configured(db)
        manager, _ = await run(db, user)
        first = load(manager.state)
        reply_id = first.actors["LINA"].reply_id
        manager, _ = await run(db, user, "Второй ход.")
        old = load(manager.state).minds["LINA"]
        future_reply = load(manager.state).actors["LINA"].reply_id
        reply = await db.get(ChatMessage, reply_id)
        reply.content = "Edited source"
        await db.commit()
        manager, chunks = await run(db, user, "Третий ход.")
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        current = load(manager.state).minds["LINA"]
        assert current.genesis == old.genesis
        assert reply_id not in {source.message_id for source in current.sources.values()}
        assert future_reply not in {source.message_id for source in current.sources.values()}
        assert future_reply not in {
            item["source_message_id"]
            for item in roles.proposal_inputs[-1]["witnessed_utterances_not_world_facts"]
        }


@pytest.mark.parametrize("mode", ["off", "shadow"])
async def test_inactive_modes_never_write_the_psychological_core(monkeypatch, mode):
    roles_for(monkeypatch)
    async with TestSessionLocal() as db:
        user, _ = await configured(db, mode)
        manager, chunks = await run(db, user)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert load(manager.state).minds == {}
