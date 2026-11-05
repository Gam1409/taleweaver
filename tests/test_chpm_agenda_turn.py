"""Exercise declared commitments through the real recoverable VN turn boundary."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn

PROMISE = "Я обещаю принести карту завтра."
DONE = "Я уже принесла обещанную карту."


class AgendaRoles(ChpmRoles):
    async def simple(self, system, payload, model, **kwargs):
        result = json.loads(await super().simple(system, payload, model, **kwargs))
        if kwargs.get("phase") == "proposal":
            supplied = self.proposal_inputs[-1]
            active = supplied["declared_agenda_not_world_facts"]
            change = {"action": "commitment", "text": "Bring a map tomorrow", "entry_id": None}
            if active:
                change = {
                    "action": "report_done",
                    "text": active[0]["text"],
                    "entry_id": active[0]["id"],
                }
            result["candidates"][0]["agenda_change"] = change
        if kwargs.get("phase") == "validation":
            speech = DONE if len(self.proposal_inputs) > 1 else PROMISE
            evidence = {"actor_id": "LINA", "quote": speech}
            result["evidence"] = [evidence]
            result["agenda_evidence"] = [evidence]
        return json.dumps(result, ensure_ascii=False)

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        speech = DONE if len(self.proposal_inputs) > 1 else PROMISE

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=f'Лина: "{speech}"'))])

        return chunks()


@pytest.mark.parametrize("mode", ["shadow", "live"])
async def test_declared_commitment_survives_zero_memory_without_world_effects(monkeypatch, mode):
    roles = AgendaRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=Settings(mode=mode, actor_ids=["LINA"], memory_limit=0)
            ).model_dump(),
        }
        original_quests = deepcopy(state.quests)
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        first = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(chunk.startswith("event: final") for chunk in first), "".join(first)
        saved = load(manager.state)
        assert saved.memories["LINA"] == []
        if mode == "shadow":
            assert saved.agenda == []
            assert roles.chpm_calls == ["perception", "proposal"]
            return
        assert len(saved.agenda) == 1 and saved.agenda[0].source.quote == PROMISE
        assert saved.agenda[0].closure is None
        manager = GameTurnManager(db, "session-1", user)
        second = [chunk async for chunk in manager.process_turn("Ты принесла карту?")]
        assert any(chunk.startswith("event: final") for chunk in second), "".join(second)
        active = roles.proposal_inputs[1]["declared_agenda_not_world_facts"]
        assert active[0]["id"] == saved.agenda[0].id
        assert roles.proposal_inputs[1]["witnessed_utterances_not_world_facts"] == []
        final = load(manager.state)
        assert len(final.agenda) == 1
        assert final.agenda[0].closure.reason == "report_done"
        assert final.agenda[0].closure.source.quote == DONE
        assert manager.state.quests == original_quests
        assert roles.chpm_calls == ["perception", "proposal", "validation"] * 2
