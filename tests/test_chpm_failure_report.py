"""Proposal rejection details survive recovery without restoring psychological state."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from backend.engine.chpm import continuation, inference, proposal_attempt
from backend.engine.chpm.errors import ChpmError, RecoverableChpmError
from backend.engine.chpm.failure_report import latest
from backend.engine.chpm.recovery_contracts import SimplifiedReply
from backend.engine.chpm.schema import KernelState, Settings, Usage
from backend.engine.chpm.state import KEY, load
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world
from tests.test_chpm_fallback import continuing
from tests.test_session_portraits import portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-session/chpm"
FEEDBACK = "candidates.refuse.preconditions: Field required"


def test_rejected_proposal_feedback_survives_a_cooldown_commit():
    host, turn = continuing()
    turn.usage.proposal_feedback = [FEEDBACK]
    continuation.activate(turn, "analysis_failed")
    turn.simplified_text = "A completed reply."
    reply = SimpleNamespace(
        id="failed-reply",
        session_id="session",
        role="assistant",
        content=turn.simplified_text,
        revision_id=None,
    )
    continuation.finish(host, turn, reply)
    turn.initial = load(host.state)
    turn.usage = Usage()
    continuation.activate(turn, "cooldown")
    reply.id = "cooldown-reply"
    continuation.finish(host, turn, reply)
    saved = load(host.state)
    assert saved.usage.proposal_feedback == []
    assert saved.recovery.recent[-2].model_dump().get("proposal_feedback") == [FEEDBACK]
    assert saved.recovery.recent[-1].model_dump().get("proposal_feedback") == []
    assert saved.minds == turn.initial.minds


@pytest.mark.parametrize("foreign", [False, True])
async def test_legacy_failure_is_read_from_same_session_snapshot_without_writes(
    auth_client, chpm_world, foreign
):
    prior = KernelState(settings=Settings(mode="live", actor_ids=["NPC_NEW"]))
    prior.usage = Usage(
        simplified=True,
        status="failed",
        fallback_reason="analysis_failed",
        proposal_feedback=[FEEDBACK],
    )
    prior.recovery.pending_gap_turns = 1
    current = prior.model_copy(deep=True)
    current.usage = Usage(simplified=True, status="failed", fallback_reason="cooldown")
    current.recovery.pending_gap_turns = 2
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        before = {
            "version": 1,
            "state": {
                "session_id": "another-session" if foreign else "portrait-session",
                "entity_states": {KEY: prior.model_dump()},
            },
        }
        db.add(
            TurnReplay(
                session_id="portrait-session", before=before, input_text="Wait.", status="ready"
            )
        )
        await db.commit()
        original = deepcopy(state.entity_states)
    response = await auth_client.get(PATH)
    assert response.status_code == 200, response.text
    report = response.json().get("last_proposal_failure")
    if foreign:
        assert report is None
    else:
        assert report is not None
        assert report["proposal_feedback"] == [FEEDBACK]
        assert report["source"] == "previous_turn_snapshot"
        assert response.json()["usage"]["proposal_feedback"] == []
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == original
        assert (await db.get(TurnReplay, "portrait-session")).before == before


async def test_feedback_window_matches_its_persisted_limit_across_npcs(monkeypatch):
    class Reply(BaseModel):
        pass

    usage = Usage(proposal_repairs=1, proposal_feedback=["Older rejection", "Previous rejection"])
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=Reply()))

    def reject(_):
        raise ChpmError("Current rejection")

    with pytest.raises(RecoverableChpmError):
        await proposal_attempt.request(
            SimpleNamespace(), Settings(), usage, "Policy", {}, Reply, {}, reject
        )
    assert usage.proposal_feedback == ["Previous rejection", "Current rejection"]
    assert Usage.model_validate(usage.model_dump()) == usage


async def test_saved_recovery_feedback_does_not_need_a_snapshot_or_model():
    current = KernelState(settings=Settings(mode="live", actor_ids=["npc"]))
    current.recovery.pending_gap_turns = 3
    current.recovery.recent = [
        SimplifiedReply(
            input_id="input",
            reply_id="failed-reply",
            reply_hash="hash",
            reason="analysis_failed",
            actor_ids=["npc"],
            proposal_feedback=[FEEDBACK],
        )
    ]
    db = SimpleNamespace(get=AsyncMock(side_effect=AssertionError("No snapshot read needed")))
    report = await latest(db, SimpleNamespace(session_id="session"), current)
    assert report["source"] == "recent_turn"
    assert report["proposal_feedback"] == [FEEDBACK]
    db.get.assert_not_awaited()


def test_legacy_recovery_records_load_without_a_schema_bump():
    raw = KernelState().model_dump()
    raw["recovery"]["recent"] = [
        {
            "input_id": "input",
            "reply_id": "reply",
            "reply_hash": "hash",
            "reason": "analysis_failed",
            "actor_ids": ["npc"],
        }
    ]
    restored = KernelState.model_validate(raw)
    assert restored.schema_version == raw["schema_version"]
    assert restored.recovery.recent[0].proposal_feedback == []
