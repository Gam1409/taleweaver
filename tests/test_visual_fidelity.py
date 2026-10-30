"""Synthetic neutral scenes and opt-in diagnostic privacy."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core import visual_trace
from backend.core.config import settings
from backend.engine.clothing.frames import Figure, VisibleFrame, compose_frame, extract_frame


@pytest.mark.parametrize(
    "position, expected", [("unspecified", "beside the window"), ("left", "left")]
)
def test_frame_preserves_lighting_and_known_position_without_inventing_action(position, expected):
    frame = VisibleFrame(figures=[Figure(character_id="NURSE", position=position)])
    cast = [
        {
            "id": "NURSE",
            "appearance": "brown hair",
            "clothing": "blue coat",
            "position": "beside the window",
        }
    ]
    result = compose_frame(frame, cast, "hospital room", lighting="warm bedside lamp")
    assert result["lighting"] == "warm bedside lamp"
    assert result["characters"][0]["position"] == expected
    assert result["characters"][0]["action"] == "unspecified"
    assert result["characters"][0]["clothing"] == "blue coat"


@pytest.mark.asyncio
async def test_long_passage_keeps_final_departure(monkeypatch):
    from backend.engine.clothing import frames

    llm = SimpleNamespace(
        model="test", aexecute_complex_task=AsyncMock(return_value=VisibleFrame())
    )
    monkeypatch.setattr(frames.GameMasterLLM, "for_role", lambda *args: llm)
    passage = (
        "Two adults are holding hands. "
        + "Earlier conversation. " * 1000
        + "She releases his hand and leaves the room."
    )
    await extract_frame(object(), passage, [{"id": "A"}])
    sent = json.loads(llm.aexecute_complex_task.call_args.args[1])["passage"]
    assert len(sent) == 16000
    assert sent.endswith("She releases his hand and leaves the room.")
    assert not sent.startswith("Two adults are holding hands.")


@pytest.fixture
def trace_directory(monkeypatch, tmp_path):
    path = tmp_path / "private-traces"
    monkeypatch.setattr(visual_trace, "DIRECTORY", path)
    monkeypatch.setattr(settings, "VISUAL_TRACE_ENABLED", True)
    monkeypatch.setattr(settings, "VISUAL_TRACE_CONTENT_ENABLED", False)
    return path


@pytest.mark.asyncio
async def test_disabled_trace_does_not_create_files(trace_directory, monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_TRACE_ENABLED", False)
    monkeypatch.setattr(settings, "VISUAL_TRACE_CONTENT_ENABLED", True)

    @visual_trace.traced
    async def run():
        visual_trace.record("input", text="PRIVATE_SCENE")
        return 42

    assert await run() == 42
    assert not trace_directory.exists()


@pytest.mark.asyncio
async def test_metadata_trace_has_no_private_content_or_exception_text(trace_directory):
    @visual_trace.traced
    async def run():
        visual_trace.record("input", text="PRIVATE_SCENE")
        raise ValueError("SECRET_TOKEN")

    with pytest.raises(ValueError):
        await run()
    text = next(trace_directory.glob("*.jsonl")).read_text()
    assert "PRIVATE_SCENE" not in text
    assert "SECRET_TOKEN" not in text
    assert "failed" in text
    assert "sha256" in text
    visual_trace.record("outside", text="OUTSIDE")
    assert "OUTSIDE" not in next(trace_directory.glob("*.jsonl")).read_text()


@pytest.mark.asyncio
async def test_content_traces_are_explicit_and_concurrent_requests_stay_separate(
    trace_directory, monkeypatch
):
    monkeypatch.setattr(settings, "VISUAL_TRACE_CONTENT_ENABLED", True)

    @visual_trace.traced
    async def run(value):
        visual_trace.record("input", text=value)
        await asyncio.sleep(0)
        visual_trace.record("output", text=value)

    await asyncio.gather(run("SCENE_A"), run("SCENE_B"))
    files = list(trace_directory.glob("*.jsonl"))
    assert len(files) == 2
    for path in files:
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        assert len({entry["trace_id"] for entry in entries}) == 1
        assert ("SCENE_A" in path.read_text()) != ("SCENE_B" in path.read_text())


@pytest.mark.asyncio
async def test_unwritable_storage_does_not_break_generation(trace_directory):
    trace_directory.write_text("not a directory")

    @visual_trace.traced
    async def run():
        return "generated"

    assert await run() == "generated"


@pytest.mark.asyncio
async def test_snapshot_keeps_end_and_preserves_message_hash():
    from contextlib import nullcontext

    from backend.engine.scene_illustrations.snapshots import (
        MAX_NARRATION,
        capture_scene_snapshot,
        content_hash,
        registry_of,
    )

    state = SimpleNamespace(id=1, session_id="session", entity_states={})
    message = SimpleNamespace(
        id="message",
        session_id="session",
        role="assistant",
        scene_id="room",
        sequence_id=None,
        content="Earlier scene. " * 2000
        + "The visitor leaves. The nurse stands alone at the window.",
    )
    db = SimpleNamespace(no_autoflush=nullcontext(), scalar=AsyncMock(return_value=None))
    await capture_scene_snapshot(db, state, message, {"lighting": "warm lamp"})
    snapshot = registry_of(state.entity_states)["snapshots"]["message"]
    assert snapshot["narration"] == message.content[-MAX_NARRATION:]
    assert snapshot["content_hash"] == content_hash(message)
    assert snapshot["visible_facts"]["lighting"] == "warm lamp"


@pytest.mark.asyncio
@pytest.mark.parametrize("style", ["tags", "description", "hybrid"])
async def test_word_budget_does_not_cut_final_action_or_negation(monkeypatch, style):
    from backend.core.image_prompt_rules import ImagePromptRules
    from backend.engine import image_prompt_adapter

    body = "Two adults in a hospital room under a warm bedside lamp.\nThe nurse steps away; their hands are not touching."
    llm = SimpleNamespace(model="test", aexecute_simple_task=AsyncMock(return_value=body))
    monkeypatch.setattr(image_prompt_adapter.GameMasterLLM, "for_role", lambda *args: llm)
    policy = ImagePromptRules(format=style, max_words=10)
    result = await image_prompt_adapter.adapt_body("Neutral scene", policy, object())
    assert result == body
    assert '"max_words": 10' in llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    assert llm.aexecute_simple_task.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", " ", "x" * 12001])
async def test_invalid_prompt_fails_instead_of_sending_partial_content(monkeypatch, body):
    from backend.core.image_prompt_rules import ImagePromptRules
    from backend.engine import image_prompt_adapter

    llm = SimpleNamespace(model="test", aexecute_simple_task=AsyncMock(return_value=body))
    monkeypatch.setattr(image_prompt_adapter.GameMasterLLM, "for_role", lambda *args: llm)
    with pytest.raises(ValueError, match="empty or invalid"):
        await image_prompt_adapter.adapt_body("Neutral scene", ImagePromptRules(), object())
