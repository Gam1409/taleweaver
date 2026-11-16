"""AI Fix must not silently shorten the configured model-role deadline."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel

from backend.api.routes.adventures.editing import ai_fix_llm
from backend.core.config import Settings


async def test_default_ai_fix_deadline_follows_the_selected_router(monkeypatch):
    observed = []

    async def wait(awaitable, timeout):
        observed.append(timeout)
        return await awaitable

    monkeypatch.setattr(asyncio, "wait_for", wait)
    gm = SimpleNamespace(request_timeout=600, aexecute_complex_task=AsyncMock(return_value="done"))
    result = await ai_fix_llm._call_provider(
        gm,
        provider="custom_openai",
        model="local",
        user_prompt="Describe a coat.",
        response_model=BaseModel,
        gm_kwargs={"system_prompt": "Return structured suggestions."},
        timeout_seconds=None,
    )
    assert result == "done"
    assert observed == [600]
    assert Settings.model_fields["AI_FIX_SUGGEST_TIMEOUT_SECONDS"].default is None


async def test_explicit_ai_fix_watchdog_is_preserved(monkeypatch):
    observed = []

    async def wait(awaitable, timeout):
        observed.append(timeout)
        return await awaitable

    monkeypatch.setattr(asyncio, "wait_for", wait)
    gm = SimpleNamespace(request_timeout=600, aexecute_complex_task=AsyncMock(return_value="done"))
    await ai_fix_llm._call_provider(
        gm,
        provider="custom_openai",
        model="local",
        user_prompt="Describe a coat.",
        response_model=BaseModel,
        gm_kwargs={"system_prompt": "Return structured suggestions."},
        timeout_seconds=45,
    )
    assert observed == [45]
