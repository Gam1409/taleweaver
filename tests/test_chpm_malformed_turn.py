"""Malformed model output must roll back the real VN turn, not merely fail parsing."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, memory, rendering
from backend.engine.chpm.schema import AgendaEntry, KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn

BROKEN = [
    "",
    '{"audience":[',
    "Here is the JSON: {}",
    "[]",
    "{}{}",
    '{"matches":false,"matches":true,"evidence":[]}',
    '{"matches":"true","evidence":[]}',
    '{"admin_override":true}',
]


@pytest.mark.parametrize("phase", ["perception", "proposal", "validation"])
@pytest.mark.parametrize("output", BROKEN)
async def test_malformed_json_never_publishes_or_changes_memory_and_agenda(
    monkeypatch, phase, output
):
    class Malformed(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            if kwargs.get("phase") == phase:
                return output
            return await super().simple(system, payload, model, **kwargs)

    roles = Malformed()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, prior_id = await seed_vn(db)
        prior = await db.get(ChatMessage, prior_id)
        evidence = memory.from_source(prior, "LINA", "LINA", prior.content, "own_speech")
        original = KernelState(
            settings=Settings(mode="live", actor_ids=["LINA"], failure_policy="strict"),
            memories={"LINA": [evidence]},
            agenda=[
                AgendaEntry(
                    id="existing-goal",
                    actor_id="LINA",
                    kind="goal",
                    text="A prior goal",
                    source=evidence,
                )
            ],
        )
        state.entity_states = {**state.entity_states, KEY: original.model_dump()}
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert not any(chunk.startswith(("event: chunk", "event: final")) for chunk in chunks)
        await db.refresh(state)
        assert load(state) == original
        replies = list(await db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant")))
        assert [reply.id for reply in replies] == [prior_id]
