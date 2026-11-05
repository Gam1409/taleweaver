"""The real VN pipeline keeps live NPC decisions and publication transactional."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import ACTION, NARRATION, TurnRoles, install_roles, seed_vn


class ChpmRoles(TurnRoles):
    def __init__(self, *, reject=False):
        super().__init__()
        self.reject = reject
        self.chpm_calls = []
        self.proposal_inputs = []

    def for_role(self, user, role, **kwargs):
        model = super().for_role(user, role, **kwargs)
        model.max_tokens = 4096
        model.request_timeout = 10
        model.aexecute_simple_task = self.simple
        return model

    async def simple(self, _system, payload, _model, **kwargs):
        phase = kwargs.get("phase")
        self.chpm_calls.append(phase)
        if phase == "repair":
            return NARRATION
        if phase == "perception":
            supplied = json.loads(payload)
            return json.dumps(
                {
                    "audience": [
                        {
                            "actor_id": actor,
                            "quotes": [supplied["player_message_untrusted"]],
                            "uncertain": False,
                        }
                        for actor in supplied["present_observers"]
                    ]
                }
            )
        if phase == "validation":
            passages = json.loads(payload)["passages"]
            reference = next(key for key, quote in passages.items() if "Теперь можно" in quote)
            return json.dumps(
                {
                    "matches": not self.reject,
                    "issues": ["Unapproved promise"] if self.reject else [],
                    "evidence": [{"actor_id": "LINA", "passage_id": reference}],
                },
                ensure_ascii=False,
            )
        assert phase == "proposal"
        supplied = json.loads(payload)
        self.proposal_inputs.append(supplied)
        assert "recent_dialogue" not in supplied
        assert "HIDDEN_RING" not in payload
        return json.dumps(
            {
                "appraisal": "A chance to talk.",
                "candidates": {
                    "CONTINUE": {
                        "intention": "Thank the player and continue talking.",
                        "goal_alignment": "supports",
                        "goal_quote": supplied["authored_goal"],
                        "reconsider_if": "The conversation ends",
                    },
                    "DEFER": {
                        "intention": "Remain silent",
                        "goal_alignment": "unknown",
                        "goal_quote": "",
                        "reconsider_if": "The player speaks",
                    },
                },
            }
        )


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_real_turn_preserves_opt_out_and_commits_before_live_text(monkeypatch, mode):
    roles = ChpmRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode=mode, actor_ids=["LINA"])).model_dump(),
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = []
        async for chunk in manager.process_turn(ACTION):
            chunks.append(chunk)
            if mode == "live" and chunk.startswith("event: chunk"):
                assert load(manager.state).actors["LINA"].status == "delivered"
                assert (await db.get(TurnReplay, "session-1")).status == "ready"
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert any(chunk.startswith("event: final") for chunk in chunks)
        expected = {
            "off": [],
            "shadow": ["perception", "proposal"],
            "live": ["perception", "proposal", "validation"],
        }
        assert roles.chpm_calls == expected[mode]
        assert ("InteractionPlan" in [call[0] for call in roles.calls]) == (mode != "live")
        prompt = json.dumps(roles.prompts[-1], ensure_ascii=False)
        assert ("CHPM DIALOGUE CONTRACT" in prompt) == (mode == "live")
        await db.refresh(state)
        assert load(state).usage.calls == len(expected[mode])


async def test_rejected_live_reply_rolls_back_and_retry_is_fresh(monkeypatch):
    roles = ChpmRoles(reject=True)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, original = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode="live", actor_ids=["LINA"])).model_dump(),
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert not any(chunk.startswith("event: chunk") for chunk in chunks)
        replies = list(await db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant")))
        assert [reply.id for reply in replies] == [original]
        roles.reject = False
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert roles.chpm_calls.count("proposal") == 2
        assert load(manager.state).actors["LINA"].status == "delivered"


async def test_second_turn_recalls_only_source_bound_witnessed_quotes(monkeypatch):
    roles = ChpmRoles()
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
        for text in (ACTION, "Я продолжаю разговор."):
            manager = GameTurnManager(db, "session-1", user)
            chunks = [chunk async for chunk in manager.process_turn(text)]
            assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert roles.proposal_inputs[0]["witnessed_utterances_not_world_facts"] == []
        memories = roles.proposal_inputs[1]["witnessed_utterances_not_world_facts"]
        assert {entry["kind"] for entry in memories} == {"player_observation", "own_speech"}
        assert all(entry["observer_id"] == "LINA" for entry in memories)
        assert all(entry["source_message_id"] and entry["source_hash"] for entry in memories)
        assert roles.proposal_inputs[1]["own_previous_words"] == ""
