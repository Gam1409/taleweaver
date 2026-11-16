"""Recovery has publication, source, scope and freshness boundaries of its own."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import continuation, continuation_writer, rendering, runtime
from backend.engine.chpm.errors import ChpmError, InferenceUnavailableError
from backend.engine.chpm.inference import OutputBudgetError
from backend.engine.chpm.schema import Verdict
from backend.engine.chpm.state import KEY, load
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import accept, proposed
from tests.test_chpm_host_state import mind
from tests.test_chpm_runtime import prepared


def continuing():
    host = prepared()
    turn = runtime.current(host)
    turn.initial.settings.failure_policy = "continue"
    turn.fallback_identities = {"npc": {"name": "Rin"}}
    host.state.entity_states = {KEY: turn.initial.model_dump()}
    return host, turn


async def test_known_rejected_text_gets_one_new_reply_and_no_psychological_commit(monkeypatch):
    host, turn = continuing()
    review = AsyncMock(
        return_value=Verdict(matches=False, issues=["Invented yesterday's agreement"])
    )
    monkeypatch.setattr(rendering, "_review", review)
    monkeypatch.setattr(rendering, "_repair", AsyncMock(return_value="Still invented"))
    generate = AsyncMock(return_value="A fresh ordinary response.")
    monkeypatch.setattr(continuation_writer, "generate", generate)
    result = await rendering.validate(
        host, "Invented history", completed=True, resolution="", system_prompt="Policy"
    )
    assert result == "A fresh ordinary response." and turn.simplified
    assert review.await_count == 2 and generate.await_count == 1
    assert (
        await rendering.validate(
            host, "Invented history", completed=True, resolution="", system_prompt="Policy"
        )
        == result
    )
    assert generate.await_count == 1
    reply = SimpleNamespace(
        id="reply", session_id="session", role="assistant", content=result, revision_id=None
    )
    runtime.finish(host, reply, completed=True)
    saved = load(host.state)
    assert saved.actors == {} and saved.minds == {}
    assert saved.recovery.recent[0].reply_id == "reply"


async def test_failed_last_resort_never_releases_the_original_rejected_text(monkeypatch):
    host, turn = continuing()
    original = deepcopy(host.state.entity_states)
    monkeypatch.setattr(
        rendering, "_review", AsyncMock(return_value=Verdict(matches=False, issues=["Bad fact"]))
    )
    monkeypatch.setattr(rendering, "_repair", AsyncMock(return_value="Still bad"))
    monkeypatch.setattr(
        continuation_writer, "generate", AsyncMock(side_effect=OutputBudgetError("cut off"))
    )
    with pytest.raises(OutputBudgetError):
        await rendering.validate(
            host, "Bad fact", completed=True, resolution="", system_prompt="Policy"
        )
    assert turn.simplified_text is None and host.state.entity_states == original
    with pytest.raises(ChpmError, match="ready to commit"):
        runtime.finish(host, SimpleNamespace(content="Bad fact"), completed=True)


def test_pre_gap_feelings_are_historical_even_without_advancing_game_time():
    value, _ = accept(heard(text="You must obey"), [proposed()])
    before = value.model_dump_json()
    shown = continuation.experience_view(value, {"npc": value.snapshot.cursor})
    assert shown["states"][0]["status"] == "historical_current_unknown"
    assert value.model_dump_json() == before


def test_source_retraction_cannot_mark_new_feelings_stale_when_sequence_numbers_repeat():
    host, turn = continuing()
    old, _ = accept(heard(text="You must obey"), [proposed()])
    new, _ = accept(heard(message="m2", text="You must obey"), [proposed()], message="m2")
    turn.initial.minds["npc"] = old
    turn.minds["npc"] = new
    turn.gap_cursors = {"npc": old.snapshot.cursor}
    assert old.snapshot.cursor == new.snapshot.cursor
    continuation.rebase_gap(turn, "npc")
    assert turn.gap_cursors == {"npc": 0}
    assert (
        continuation.experience_view(new, turn.gap_cursors)["states"][0]["status"]
        == "recent_appraisal"
    )


def test_fallback_never_reads_another_sessions_identity():
    host, turn = continuing()
    turn.initial.minds["npc"] = mind(session="foreign")
    actor = SimpleNamespace(id="npc", name="Rin")
    with pytest.raises(ChpmError, match="another session"):
        continuation.identities(host, turn.initial, [actor])


async def test_unavailable_reviewer_does_not_dispatch_another_model_request(monkeypatch):
    host, turn = continuing()
    monkeypatch.setattr(
        rendering, "_review", AsyncMock(side_effect=InferenceUnavailableError("uncertain"))
    )
    generate = AsyncMock(side_effect=AssertionError("No duplicate inference"))
    monkeypatch.setattr(continuation_writer, "generate", generate)
    text = "A complete narrator response with no known rejected fact."
    assert (
        await rendering.validate(host, text, completed=True, resolution="", system_prompt="Policy")
        == text
    )
    assert turn.simplified and turn.usage.fallback_reason == "review_unavailable"
    generate.assert_not_awaited()
