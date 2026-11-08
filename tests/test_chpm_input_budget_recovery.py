"""Input packing failures remain actionable without erasing identity or replaying turns."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import continuation, inference, json_contract, proposal_draft, runtime
from backend.engine.chpm.cognitive_context import ContextBudgetError
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
CAUSE = "CHPM required context exceeds its budget (26800 > 21952 characters). No decision proposal sent."


def test_lossless_wire_encoding_fits_without_raising_the_saved_input_limit():
    instruction = "Preserve the supplied words and every schema constraint."
    payload = {"quote": "Рин: «Два  пробела и новая\nстрока». ⟨text⟩", "padding": ""}
    schema = json_contract.response_schema(proposal_draft.Draft, {})
    initial_system, initial_content = inference.compose(
        instruction, payload, proposal_draft.Draft, {}
    )
    prefix = initial_system.split("JSON schema:\n", 1)[0] + "JSON schema:\n"

    base = len(initial_system) + len(initial_content)
    payload["padding"] = "P" * (24000 - base - 8)
    legacy_size = len(prefix + json.dumps(schema, ensure_ascii=False)) + len(
        json.dumps(payload, ensure_ascii=False)
    )
    assert legacy_size > 24000
    settings, usage = Settings(), Usage()
    system, content = inference.compose(instruction, payload, proposal_draft.Draft, {})
    inference.reserve(settings, usage, len(system) + len(content))
    assert json.loads(content) == payload
    assert json.loads(system.split("JSON schema:\n", 1)[1]) == schema
    assert settings.max_input_chars == 24000 and usage.calls == 1


def test_input_budget_cause_is_not_replaced_by_generic_recovery_text():
    host, turn = continuing()
    turn.usage.calls = 1
    runtime._preparation_failed(host, turn, ContextBudgetError(CAUSE))
    assert CAUSE in turn.usage.detail
    turn.simplified_text = "Ordinary narration."
    reply = SimpleNamespace(
        id="reply",
        session_id="session",
        role="assistant",
        content=turn.simplified_text,
        revision_id=None,
    )
    continuation.finish(host, turn, reply)
    saved = load(host.state)
    assert CAUSE in saved.recovery.recent[-1].model_dump().get("failure_detail", "")


def test_raw_transport_exception_messages_do_not_become_owner_diagnostics():
    _, turn = continuing()
    continuation.activate(turn, "analysis_failed", error=RuntimeError("PRIVATE_API_TOKEN"))
    assert "PRIVATE_API_TOKEN" not in turn.usage.detail


@pytest.mark.parametrize("changed", [False, True])
async def test_fixing_request_limits_allows_next_turn_to_retry_without_erasing_the_gap(
    auth_client, chpm_world, changed
):
    current = KernelState(settings=Settings(mode="live", actor_ids=["NPC_NEW"]))
    current.recovery.cooldown_remaining = 3
    current.recovery.consecutive_failures = 4
    current.recovery.pending_gap_turns = 18
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        before = {
            "version": 1,
            "state": {
                "session_id": "portrait-session",
                "entity_states": deepcopy(state.entity_states),
            },
        }
        db.add(
            TurnReplay(
                session_id="portrait-session", before=before, input_text="Wait.", status="ready"
            )
        )
        await db.commit()
    changes = {"max_input_chars": 48000, "max_calls_per_turn": 11} if changed else {}
    response = await auth_client.patch(
        PATH,
        json={
            "expected_revision": 0,
            "settings": current.settings.model_copy(update=changes).model_dump(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["continuation"]["cooldown_remaining"] == (0 if changed else 3)
    assert response.json()["continuation"]["unreviewed_turns"] == 18
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        after = load(state)
        assert after.recovery.consecutive_failures == (0 if changed else 4)
        assert after.minds == current.minds and after.agenda == current.agenda
        snapshot = (await db.get(TurnReplay, "portrait-session")).before
        assert snapshot["state"]["entity_states"][KEY]["recovery"]["cooldown_remaining"] == (
            0 if changed else 3
        )


async def test_nonproposal_failure_is_recovered_from_the_owned_snapshot(auth_client, chpm_world):
    prior = KernelState(settings=Settings(mode="live", actor_ids=["NPC_NEW"]))
    prior.usage = Usage(
        simplified=True, status="failed", fallback_reason="analysis_failed", detail=CAUSE
    )
    prior.recovery.pending_gap_turns = 18
    current = prior.model_copy(deep=True)
    current.usage = Usage(simplified=True, status="failed", fallback_reason="cooldown")
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        before = {
            "version": 1,
            "state": {"session_id": "portrait-session", "entity_states": {KEY: prior.model_dump()}},
        }
        db.add(
            TurnReplay(
                session_id="portrait-session", before=before, input_text="Wait.", status="ready"
            )
        )
        await db.commit()
    response = await auth_client.get(PATH)
    assert response.status_code == 200, response.text
    failure = response.json().get("last_analysis_failure")
    assert failure is not None
    assert failure["detail"] == CAUSE and failure["proposal_feedback"] == []
    assert response.json()["last_proposal_failure"] is None
