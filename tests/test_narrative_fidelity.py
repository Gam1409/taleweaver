"""Narration and its history retain expressive text across transport boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.llm_router import GameMasterLLM
from backend.engine.gameplay.turn_prompt_layout import format_recent_narration
from tests import test_custom_openai as endpoint_fixtures
from tests.test_custom_openai import make_router

local_policy = endpoint_fixtures.local_policy
pytestmark = pytest.mark.usefixtures("local_policy")

PROSE = (
    '\n[relieved] Lina: "Oh… <sigh><sigh><sigh> You made it!"\n\n'
    '[short pause]\nMila: "Ah—wait…"\n' + "<breath>\n" * 12 + "The silence lingered.\n"
)


def response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))], model_dump=lambda: {}
    )


def test_sync_narration_preserves_emotions_repeated_cues_and_paragraphs(monkeypatch):
    router = make_router()
    monkeypatch.setattr(router, "_completion_with_openrouter_fallback", lambda _: response(PROSE))
    assert router.execute_simple_task("Narrate", "Continue", "model") == PROSE


@pytest.mark.asyncio
async def test_async_narration_preserves_emotions_repeated_cues_and_paragraphs(monkeypatch):
    router = make_router()
    monkeypatch.setattr(
        router, "_acompletion_with_openrouter_fallback", AsyncMock(return_value=response(PROSE))
    )
    assert await router.aexecute_simple_task("Narrate", "Continue", "model") == PROSE


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 7, 1000])
@pytest.mark.parametrize("fail", [False, True])
async def test_stream_preserves_history_text_terminal_usage_and_failures(monkeypatch, size, fail):
    router = make_router()
    history = [
        {"role": "system", "content": "Narrate"},
        {"role": "assistant", "content": PROSE},
        {"role": "assistant", "content": "<sigh> <gasp>"},
        {"role": "user", "content": "Continue"},
    ]
    closed = []

    async def source():
        try:
            for start in range(0, len(PROSE), size):
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=PROSE[start : start + size]),
                            finish_reason=None,
                        )
                    ]
                )
            if fail:
                raise RuntimeError("provider failed")
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")]
            )
            yield SimpleNamespace(choices=[], usage={"total_tokens": 42})
        finally:
            closed.append(True)

    completion = AsyncMock(return_value=source())
    monkeypatch.setattr(router, "_acompletion_with_openrouter_fallback", completion)
    stream = await router.stream_simple_task("Narrate", "Continue", "model", messages=history)
    chunks = []
    try:
        async for chunk in stream:
            chunks.append(chunk)
    except RuntimeError as error:
        assert fail and str(error) == "provider failed"
    else:
        assert not fail
        assert chunks[-1].usage == {"total_tokens": 42}
        assert chunks[-2].choices[0].finish_reason == "stop"
    assert "".join(c.choices[0].delta.content or "" for c in chunks if c.choices) == PROSE
    assert completion.call_args.args[0]["messages"] == history
    assert closed == [True]


def test_story_planner_keeps_the_same_emotional_context_as_saved_narration():
    context = format_recent_narration(
        [{"role": "assistant", "content": PROSE}], for_story_initiative=True
    )
    assert PROSE.strip() in context


def test_protocol_reasoning_remains_separate_from_expressive_prose():
    assert GameMasterLLM.clean_thinking_tags("<think>private reasoning</think>Oh… <sigh>") == (
        "Oh… <sigh>"
    )
