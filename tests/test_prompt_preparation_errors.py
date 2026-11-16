"""Image tests must identify failures in their text-model dependency."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.comfyui_errors import ComfyRequestError
from backend.core.error_diagnostics import diagnose_provider_error
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.inference.registry import InferenceUncertainError
from backend.core.prompt_preparation_error import PromptPreparationError
from backend.engine import image_prompt_adapter
from backend.engine.comfyui_client import ComfyClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (RuntimeError("OpenAIException - Connection error. secret-address"), "Could not connect"),
        (InferenceUncertainError("secret-address"), "Clear stopped request"),
    ],
)
async def test_adapter_failure_identifies_text_provider(monkeypatch, failure, expected):
    llm = SimpleNamespace(
        provider="custom_openai",
        model="test-model",
        aexecute_simple_task=AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(image_prompt_adapter.GameMasterLLM, "for_role", lambda *_: llm)
    monkeypatch.setattr(image_prompt_adapter, "role_timeout", lambda *_: 10)

    with pytest.raises(PromptPreparationError) as caught:
        await image_prompt_adapter.adapt_body("A wizard portrait", ImagePromptRules(), object())

    assert caught.value.__cause__ is failure
    message = diagnose_provider_error(caught.value, provider="comfyui", context="vision")
    assert "Small/Utility" in message
    assert "No ComfyUI image job was submitted" in message
    assert expected in message
    assert "secret-address" not in message
    assert "Connection test failed for Comfyui" not in message


@pytest.mark.asyncio
async def test_workflow_rejection_keeps_safe_node_diagnostic(monkeypatch):
    monkeypatch.setattr("backend.engine.comfyui_client.validate_provider_url", lambda url: url)
    async with ComfyClient("https://example.com") as client:
        monkeypatch.setattr(
            client.http,
            "request",
            AsyncMock(
                return_value=httpx.Response(
                    400,
                    json={
                        "node_errors": {
                            "model": {
                                "class_type": "UNETLoader",
                                "errors": [{"details": "secret-path"}],
                            }
                        }
                    },
                )
            ),
        )
        with pytest.raises(ComfyRequestError) as caught:
            await client.json("POST", "/prompt", json={"prompt": {}})
    message = diagnose_provider_error(caught.value, provider="comfyui", context="vision")
    assert "HTTP 400" in message
    assert "model (UNETLoader)" in message
    assert "compatibility check" in message
    assert "secret-path" not in message
