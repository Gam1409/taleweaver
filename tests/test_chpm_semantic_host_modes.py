"""Saved VN memory remains dormant outside the matching dialogue controller."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import semantic_index
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.memory_rag.worker import _maybe_observer
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_semantic_integration import ACTORS, _run_index, semantic_world
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world", "semantic_world"]


def preferences(scope):
    return Settings(
        control_scope=scope,
        mode="live",
        actor_ids=ACTORS,
        action_tools=True,
        workflow="integrated",
        agent_steps=1,
        max_calls_per_turn=25,
        semantic_memory=True,
    )


@pytest.mark.parametrize(
    "host_mode, scope", [("rpg", "combat_actions"), ("rpg", "dialogue"), ("vn", "combat_actions")]
)
async def test_saved_psychological_memory_is_not_embedded_outside_vn_dialogue(
    semantic_world, host_mode, scope
):
    owner, base, _store, calls = semantic_world
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        template = await db.get(AdventureTemplate, state.template_id)
        template.rule_enforcement_mode = host_mode
        kernel = load(state)
        saved_minds = {key: value.model_dump_json() for key, value in kernel.minds.items()}
        kernel.settings = preferences(scope)
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
    assert not await _run_index(owner, base)
    assert calls == []
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        kernel = load(state)
        assert kernel.settings.semantic_memory is True
        assert {key: value.model_dump_json() for key, value in kernel.minds.items()} == saved_minds


async def test_background_worker_does_not_admit_hidden_combat_memory_preference(monkeypatch):
    index = AsyncMock(return_value=True)
    monkeypatch.setattr(semantic_index, "index_batch", index)
    state = SimpleNamespace(
        entity_states={KEY: KernelState(settings=preferences("combat_actions")).model_dump()}
    )
    assert not await _maybe_observer(True, SimpleNamespace(), SimpleNamespace(), state)
    index.assert_not_awaited()
