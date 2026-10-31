"""Private conversational choices never become events or overwrite narrative state."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import conversation
from backend.engine.living_world.schema import Simulation
from backend.engine.living_world.state import load, save
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests import test_living_world_decisions as decisions
from tests.conftest import TestSessionLocal

world, ready = decisions.world, decisions.ready


def test_choice_trigger_skips_chatter_and_ambiguous_speakers(monkeypatch):
    monkeypatch.setattr(conversation, "physically_present", lambda actor, state: True)
    state = SimpleNamespace(entity_states={})
    lina = SimpleNamespace(id="a", name="Лина", entity_type="NPC")
    mika = SimpleNamespace(id="b", name="Мика", entity_type="NPC")
    assert conversation.select_actor(state, "Доброе утро", [lina]) is None
    assert conversation.select_actor(state, "Помоги мне", [lina, mika]) is None
    assert conversation.select_actor(state, "Лина, помоги мне", [lina, mika]) is lina
    assert conversation.select_actor(state, "Will you help me?", [lina]) is lina
    assert conversation.select_actor(state, "[EVALUATE STATE]", [lina]) is None


async def test_choice_is_turn_local_and_failure_does_not_abort(ready, monkeypatch):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        user = await db.scalar(select(User).where(User.username == "test_user"))
        actor = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LILI"
            )
        )
        simulation = load(state)
        simulation.settings.dialogue_choices_enabled = True
        save(state, simulation)
        await db.commit()
        manager = SimpleNamespace(
            adventure=SimpleNamespace(rule_enforcement_mode="vn"),
            state=state,
            user=user,
            db=db,
            game_id="session-1",
            _turn_replay_recorded=True,
        )

        async def release(manager):
            await manager.db.commit()

        monkeypatch.setattr(conversation, "release_for_model", release)
        monkeypatch.setattr(conversation, "physically_present", lambda actor, state: True)
        before = json.dumps(state.entity_states, sort_keys=True)
        events = simulation.events.copy()

        async def generate(self, *args, **kwargs):
            assert not db.in_transaction()
            assert kwargs["operation"] == "living_world_dialogue_choice"
            return conversation.Choice(
                action="NEGOTIATE",
                motive="Needs reassurance.",
                intention="Ask for a promise first.",
            ).model_dump_json()

        monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
        block = await conversation.prepare_choice(manager, "Will you help me?", [actor])
        assert "NEGOTIATE" in block
        assert "completed action" in block
        assert json.dumps(state.entity_states, sort_keys=True) == before
        assert load(state).events == events
        assert load(state).deliberation_attempts == 1
        monkeypatch.setattr(
            GameMasterLLM, "aexecute_simple_task", AsyncMock(return_value="invalid JSON")
        )
        assert await conversation.prepare_choice(manager, "Will you help me?", [actor]) == ""
        assert load(state).deliberation_attempts == 2
        assert load(state).events == events


def test_old_settings_leave_optional_live_and_dialogue_work_disabled():
    prefs = Simulation().settings
    assert not prefs.live_enabled
    assert not prefs.dialogue_choices_enabled
    assert not prefs.allow_concurrent_requests


async def test_concordia_runs_structured_conversation_choice():
    import pytest

    from backend.engine.living_world import concordia_adapter

    if not concordia_adapter.available():
        pytest.skip("Optional Concordia package is not installed")
    calls = []

    async def choose():
        calls.append(1)
        return conversation.Choice(
            action="REFUSE", motive="Protect a promise.", intention="Decline politely."
        )

    result = await concordia_adapter.decide({"actor": {"id": "NPC"}}, choose)
    assert result.action == "REFUSE" and calls == [1]
