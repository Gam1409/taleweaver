"""Visual preprocessing uses the same deadline as its selected LLM role."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.llm_deadlines import role_timeout
from backend.engine import image_prompt_adapter
from backend.engine.clothing import frames


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [300, 600])
@pytest.mark.parametrize("provider", ["custom_openai", "ollama"])
async def test_both_visual_calls_use_configured_provider_timeout(monkeypatch, timeout, provider):
    user = SimpleNamespace(
        llm_settings={
            "small_model_provider": provider,
            "small_model": "example",
            "custom_openai_timeout": timeout,
            "small_ollama_timeout": timeout,
        }
    )
    assert role_timeout(user, "small") == timeout
    llm = SimpleNamespace(
        model="example",
        aexecute_simple_task=AsyncMock(return_value="A quiet cafe"),
        aexecute_complex_task=AsyncMock(return_value={"figures": [], "relations": []}),
    )
    monkeypatch.setattr(image_prompt_adapter.GameMasterLLM, "for_role", lambda *_: llm)
    deadlines = []

    async def wait_for(awaitable, timeout):
        deadlines.append(timeout)
        return await awaitable

    monkeypatch.setattr(image_prompt_adapter.asyncio, "wait_for", wait_for)
    await frames.extract_frame(user, "A quiet cafe", [])
    await image_prompt_adapter.adapt_body("A quiet cafe", ImagePromptRules(), user)
    assert deadlines == [timeout, timeout]
