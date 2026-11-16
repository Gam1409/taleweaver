"""An optional search hint narrows the existing recovery request, never its evidence rules."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


@pytest.mark.parametrize("role", ["small", "complex"])
async def test_search_focus_reaches_the_same_single_request_as_untrusted_context(monkeypatch, role):
    hint = 'пробирка "стеклянная" — поиск по истории'
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        llm = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(return_value=RecoveryProposal())
        )
        monkeypatch.setattr(
            "backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: llm
        )
        before = dict(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            f"wardrobe_preview LINA {role} " + json.dumps(hint, ensure_ascii=False),
            user=user,
            avatar=avatar,
        )
        assert "preview ready" in result, result
        llm.aexecute_complex_task.assert_awaited_once()
        call = llm.aexecute_complex_task.call_args
        assert json.loads(call.args[1])["recovery_focus"] == hint
        assert state.entity_states == {**before, KEY: state.entity_states[KEY]}
        assert not state.entity_states[KEY]["accepted"]


async def test_oversized_focus_does_not_start_a_model_request(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        router = AsyncMock()
        monkeypatch.setattr("backend.engine.clothing.recovery.GameMasterLLM.for_role", router)
        before = dict(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            "wardrobe_preview LINA complex " + json.dumps("x" * 401),
            user=user,
            avatar=avatar,
        )
        assert "DEBUG ERROR" in result
        router.assert_not_called()
        assert state.entity_states == before
