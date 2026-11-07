"""RP continuity never turns rejected cognitive output into confirmed psychology."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import continuation_writer, inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


@pytest.mark.parametrize("phase", ["perception", "proposal", "validation"])
async def test_completed_invalid_analysis_continues_rp_without_committing_psychology(
    monkeypatch, phase
):
    class Broken(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            if kwargs.get("phase") == phase:
                return '{"broken":'
            return await super().simple(system, payload, model, **kwargs)

    roles = Broken()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        before = KernelState(settings=Settings(mode="live", actor_ids=["LINA"]))
        state.entity_states = {**state.entity_states, KEY: before.model_dump()}
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        assert not any(c.startswith("event: error") for c in chunks), "".join(chunks)
        saved = load(manager.state)
        assert saved.minds == before.minds and saved.actors == before.actors
        assert saved.memories == before.memories and saved.agenda == before.agenda
        assert saved.usage.simplified and saved.recovery.pending_gap_turns == 1
        final = json.loads(
            next(c for c in chunks if c.startswith("event: final")).split("data: ", 1)[1]
        )
        assert final["npc_behavior"]["quality"] == "simplified"
        assert final["npc_behavior"]["module_version"] == "1.2.0"
        assert (await db.get(TurnReplay, "session-1")).status == "ready"
        replies = list(await db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant")))
        assert len(replies) == 2


def test_legacy_settings_gain_continuity_without_a_saved_schema_bump():
    raw = KernelState().model_dump()
    raw["settings"].pop("failure_policy", None)
    raw.pop("recovery", None)
    restored = KernelState.model_validate(raw)
    assert restored.schema_version == 6
    assert getattr(restored.settings, "failure_policy", None) == "continue"
    assert restored.recovery.pending_gap_turns == 0


async def test_repeated_failures_pause_analysis_and_return_without_stale_intention(monkeypatch):
    class Toggle(ChpmRoles):
        broken = False

        async def simple(self, system, payload, model, **kwargs):
            if self.broken and kwargs.get("phase") == "proposal":
                return '{"broken":'
            return await super().simple(system, payload, model, **kwargs)

    roles = Toggle()
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

        async def play():
            manager = GameTurnManager(db, "session-1", user)
            chunks = [c async for c in manager.process_turn(ACTION)]
            assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
            return load(manager.state)

        confirmed = await play()
        roles.broken = True
        for _ in range(2):
            simplified = await play()
            assert simplified.minds == confirmed.minds and simplified.actors == confirmed.actors
        assert simplified.recovery.cooldown_remaining == 3
        for remaining in (2, 1, 0):
            simplified = await play()
            assert simplified.usage.calls == 0
            assert simplified.recovery.cooldown_remaining == remaining
        assert simplified.recovery.pending_gap_turns == 5
        roles.broken = False
        resumed = await play()
        assert resumed.usage.status == "validated" and not resumed.usage.simplified
        assert resumed.recovery.pending_gap_turns == 0
        assert roles.proposal_inputs[-1]["previous_intention"] is None
        assert roles.proposal_inputs[-1]["continuity_gap"]["unreviewed_turns"] == 5
        assert resumed.minds["LINA"].genesis == confirmed.minds["LINA"].genesis


async def test_rejected_narration_uses_real_ordinary_writer_once_and_commits_afterwards(
    monkeypatch,
):
    class Rejecting(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            if kwargs.get("phase") == "rp_continuation":
                self.chpm_calls.append("rp_continuation")
                data = json.loads(payload)
                assert "TURN RESOLUTION" in data["current_scene_and_resolution"]
                assert data["review_issues_to_avoid"] == ["Unapproved promise"]
                assert "narration" not in data
                assert "CHPM DIALOGUE CONTRACT" not in str(kwargs["messages"])
                return "Лина: «Давай продолжим разговор»."
            return await super().simple(system, payload, model, **kwargs)

    roles = Rejecting(reject=True)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    monkeypatch.setattr(continuation_writer, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode="live", actor_ids=["LINA"])).model_dump(),
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [c async for c in manager.process_turn(ACTION)]
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        saved = load(manager.state)
        assert saved.usage.fallback_requests == 1 and saved.minds == {}
        assert roles.chpm_calls.count("validation") == 2
        assert roles.chpm_calls.count("repair") == 1
        assert roles.chpm_calls.count("rp_continuation") == 1
