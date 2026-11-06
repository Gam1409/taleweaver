"""Progression wall time excludes host resolution; diagnostics never contain RP text."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from backend.engine.gameplay import progression_request
from backend.engine.gameplay.turn_prompt_layout import build_pass1_user_prompt


class Result(BaseModel):
    done: bool = False


@pytest.mark.parametrize("outcome", ["ok", "error", "cancel"])
async def test_request_records_size_and_wall_time_without_changing_outcome(monkeypatch, outcome):
    events = []
    ticks = iter([1.0, 3.5])
    monkeypatch.setattr(progression_request.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        progression_request,
        "log_structured_event",
        lambda event, **fields: events.append((event, fields)),
    )
    response = Result(done=True)
    llm = SimpleNamespace(aexecute_complex_task=AsyncMock(return_value=response))
    if outcome != "ok":
        llm.aexecute_complex_task.side_effect = (
            RuntimeError("private text") if outcome == "error" else asyncio.CancelledError()
        )
    host = SimpleNamespace(adventure=SimpleNamespace(id="adventure"), game_id="session")
    call = progression_request.request(
        host, llm, "private system", "private story", Result, model="model"
    )
    if outcome == "ok":
        assert await call is response
    else:
        with pytest.raises(RuntimeError if outcome == "error" else asyncio.CancelledError):
            await call
    assert llm.aexecute_complex_task.await_count == 1
    assert llm.aexecute_complex_task.call_args.kwargs["phase"] == "chat_progression"
    assert [name for name, _ in events] == ["gm.turn.pipeline.context", "gm.turn.pipeline.pass"]
    assert events[0][1]["chars"] > len("private systemprivate story")
    assert events[1][1]["duration_ms"] == 2500
    assert "private" not in repr(events)


def test_progression_input_does_not_grow_with_identical_current_state_and_more_old_turns():
    last = {"role": "assistant", "content": "Rin entered the laboratory."}
    recent = build_pass1_user_prompt("Current state", "Well?", [last], for_story_initiative=True)
    older = [{"role": "assistant", "content": "Earlier scene. " * 1000}] * 100
    extended = build_pass1_user_prompt(
        "Current state", "Well?", [*older, last], for_story_initiative=True
    )
    assert extended == recent
