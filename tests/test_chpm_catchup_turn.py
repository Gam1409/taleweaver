"""Exercise history recovery in the complete transactional VN turn, without extra calls."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


class RecoveringRoles(ChpmRoles):
    broken = True

    async def simple(self, system, payload, model, **kwargs):
        if self.broken and kwargs.get("phase") == "perception":
            return '{"broken":'
        result = await super().simple(system, payload, model, **kwargs)
        supplied = json.loads(payload)
        if kwargs.get("phase") != "perception" or "unreviewed_history" not in supplied:
            return result
        decoded = json.loads(result)
        decoded["history_fragments"] = {
            key: {"kind": "speech", "speaker_id": "LINA", "observers": ["LINA"]}
            for key in supplied["unreviewed_history"]["fragments"]
        }
        return json.dumps(decoded)


@pytest.mark.parametrize("reject", [False, True])
async def test_simplified_reply_is_recovered_only_with_a_later_successful_shared_review(
    monkeypatch, reject
):
    roles = RecoveringRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode="live", actor_ids=["LINA"])).model_dump(),
        }
        await db.commit()
        first = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in first.process_turn(ACTION)]
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        source = await db.scalar(select(ChatMessage).where(ChatMessage.npc_recovery.is_not(None)))
        assert source is not None and source.npc_recovery["actors"] == {"LINA": 0}
        roles.broken, roles.reject = False, reject
        roles.chpm_calls.clear()
        if reject:
            confirmed = load(first.state)
            confirmed.settings.failure_policy = "strict"
            first.state.entity_states = {**first.state.entity_states, KEY: confirmed.model_dump()}
            await db.commit()
        second = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in second.process_turn(ACTION)]
        await db.refresh(source)
        if reject:
            assert any(chunk.startswith("event: error") for chunk in chunks)
            assert source.npc_recovery["actors"] == {"LINA": 0}
            return
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
        recovered = [
            entry for entry in load(second.state).minds["LINA"].sources.values() if entry.history
        ]
        assert recovered and all(entry.message_id == source.id for entry in recovered)
        assert all(
            entry.history.evidence_span.matches(source.content, entry.text) for entry in recovered
        )
        assert source.npc_recovery["actors"] == {}
