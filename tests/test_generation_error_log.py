"""Token-limit diagnostics and the server-side generation error log."""

import pytest
from pydantic import BaseModel

from backend.api.routes.adventures.editing.ai_fix_llm import _candidate_attempts
from backend.core.generation_error_log import format_creation_error, record_generation_error
from backend.core.llm_errors import LLMTruncatedResponseError
from backend.models.user import User


class _MiniSchema(BaseModel):
    required: str


def _fake_response(content: str, finish_reason: str, usage: dict):
    class _Msg:
        pass

    msg = _Msg()
    msg.content = content

    class _Choice:
        message = msg

    choice = _Choice()
    choice.finish_reason = finish_reason

    class _Resp:
        choices = [choice]
        model = "google/gemini-test"

        @staticmethod
        def model_dump():
            return {}

    resp = _Resp()
    resp.usage = usage
    return resp


@pytest.mark.asyncio
async def test_truncation_error_reports_category_budget_and_actual_usage(monkeypatch):
    # Arrange
    from backend.core.llm_router import GameMasterLLM

    user = User(
        username="tester",
        llm_settings={"generator_max_tokens": 200000},
        encrypted_api_keys={"deepseek": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-test",
    )
    router = GameMasterLLM(user, provider="deepseek", model_category="generator")
    usage = {
        "prompt_tokens": 5000,
        "completion_tokens": 8192,
        "completion_tokens_details": {"reasoning_tokens": 1024},
    }
    response = _fake_response('{ "required": "cut of', "length", usage)

    async def fake_acompletion(**kwargs):
        assert kwargs["max_tokens"] == 200000
        return response

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    # Act
    with pytest.raises(LLMTruncatedResponseError) as exc_info:
        await router.aexecute_complex_task(
            system_prompt="sys", user_prompt="prompt", response_model=_MiniSchema, model="m"
        )

    # Assert
    message = str(exc_info.value)
    assert "token limit" in message.lower()
    assert "World Generator" in message
    assert "200000" in message and "8192" in message
    assert "lower output cap" in message
    diagnostics = exc_info.value.diagnostics
    assert diagnostics["model_category"] == "generator"
    assert diagnostics["completion_tokens"] == 8192
    assert diagnostics["reasoning_tokens"] == 1024
    assert diagnostics["finish_reason"] == "length"


def test_record_generation_error_writes_server_log_without_leaking_traceback(
    isolated_generation_error_log,
):
    # Arrange
    def _fail():
        raise LLMTruncatedResponseError("token limit hit", {"max_tokens": 10368})

    # Act
    try:
        _fail()
    except LLMTruncatedResponseError as exc:
        entry = record_generation_error(exc, stage="ai_validation", template_id="tpl-1")

    # Assert
    error_id = entry["details"]["error_id"]
    assert entry["type"] == "error"
    assert entry["content"] == "token limit hit"
    assert entry["details"]["diagnostics"] == {"max_tokens": 10368}
    assert "Traceback" not in str(entry)
    log_text = isolated_generation_error_log.read_text(encoding="utf-8")
    assert error_id in log_text
    assert "tpl-1" in log_text
    assert "Traceback" in log_text and "_fail" in log_text


def test_format_creation_error_includes_id_and_respects_column_limit():
    # Arrange
    entry = {"content": "x" * 1000, "details": {"error_id": "abc123"}}

    # Act
    text = format_creation_error(entry)

    # Assert
    assert text.startswith("[Error ID abc123]")
    assert len(text) == 500


def test_ai_fix_small_model_fallback_uses_small_token_budget():
    # Arrange
    user = User(
        username="tester",
        llm_settings={
            "complex_model_provider": "openrouter",
            "complex_model": "complex-m",
            "small_model_provider": "openrouter",
            "small_model": "small-m",
        },
    )

    # Act
    attempts = _candidate_attempts(user, allow_fallback=False)

    # Assert
    assert attempts == [
        ("openrouter", "complex-m", "complex"),
        ("openrouter", "small-m", "small"),
    ]
