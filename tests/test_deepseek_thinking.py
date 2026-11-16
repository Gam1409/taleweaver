"""Native DeepSeek uses one explicit thinking mode for text and JSON requests."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


class Answer(BaseModel):
    value: str


def router(monkeypatch, enabled):
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_: "test-key")
    user = User(
        llm_settings={
            "small_model_provider": "deepseek",
            "small_model": "deepseek-flash",
            "small_enable_thinking": enabled,
            "small_max_thinking_tokens": 1024,
        }
    )
    return GameMasterLLM.for_role(user, "small")


@pytest.mark.parametrize("enabled", [False, True])
def test_structured_json_uses_the_same_chat_endpoint_and_explicit_thinking(monkeypatch, enabled):
    client = router(monkeypatch, enabled)
    request = client._build_structured_request("Return JSON.", "input", Answer, client.model)
    assert request.kwargs["thinking"] == {"type": "enabled" if enabled else "disabled"}
    assert request.kwargs["response_format"] == {"type": "json_object"}
    assert request.kwargs["api_base"] == "https://api.deepseek.com"
    assert "JSON" in request.kwargs["messages"][0]["content"]
    assert "value" in request.kwargs["messages"][0]["content"]
    assert request.kwargs["max_tokens"] == client.max_tokens


@pytest.mark.parametrize("enabled", [False, True])
async def test_real_text_and_structured_router_send_the_mode_to_litellm(monkeypatch, enabled):
    client = router(monkeypatch, enabled)
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"value":"ok"}'), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", complete)
    assert await client.aexecute_simple_task("system", "input", client.model) == '{"value":"ok"}'
    result = await client.aexecute_complex_task("system", "input", Answer, client.model)
    assert result == Answer(value="ok")
    assert len(calls) == 2
    for call in calls:
        assert call["thinking"] == {"type": "enabled" if enabled else "disabled"}
        assert call["api_base"] == "https://api.deepseek.com"


@pytest.mark.parametrize("enabled", [False, True])
def test_installed_litellm_preserves_the_explicit_mode_on_the_wire(monkeypatch, enabled):
    from litellm.llms.deepseek.chat.transformation import DeepSeekChatConfig

    client = router(monkeypatch, enabled)
    options = {}
    client._apply_thinking_settings(options)
    wire = DeepSeekChatConfig().map_openai_params(options, {}, client.model, False)
    assert wire["thinking"] == {"type": "enabled" if enabled else "disabled"}
