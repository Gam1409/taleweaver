"""Structured admission measures the complete prepared wire contract before sending."""

import json
from unittest.mock import Mock

import httpx
import pytest

from tests.test_llm_structured_single_attempt import Answer, completion, mock_http, router


def input_size(kwargs):
    return len(
        json.dumps(
            {
                key: kwargs[key]
                for key in ("messages", "tools", "tool_choice", "response_format")
                if key in kwargs
            },
            ensure_ascii=False,
        )
    )


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
@pytest.mark.parametrize("single_attempt", [False, True])
async def test_exact_prepared_budget_builds_once_and_preserves_typed_result(
    monkeypatch, mode, single_attempt
):
    async def respond(request):
        return httpx.Response(200, json=completion(), request=request)

    llm = router(monkeypatch, mode)
    text = "Проверить 明日"
    prepared = llm._build_structured_request("sys", text, Answer, "local-model")
    measured = input_size(prepared.kwargs)
    build = Mock(wraps=llm._build_structured_request)
    log = Mock(wraps=llm._log_structured_request)
    monkeypatch.setattr(llm, "_build_structured_request", build)
    monkeypatch.setattr(llm, "_log_structured_request", log)
    seen = mock_http(monkeypatch, respond)
    result = await llm.aexecute_complex_task(
        "sys", text, Answer, "local-model", max_input_chars=measured, single_attempt=single_attempt
    )
    assert result == Answer(value=7) and len(seen) == 1
    assert build.call_count == log.call_count == 1
    assert input_size(json.loads(seen[0].content)) == measured


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
@pytest.mark.parametrize("single_attempt", [False, True])
async def test_prepared_budget_rejects_before_logging_or_http(monkeypatch, mode, single_attempt):
    async def unexpected(_request):
        raise AssertionError("An oversized prepared request must not be sent.")

    llm = router(monkeypatch, mode)
    canary = "PRIVATE_INPUT_BUDGET_CANARY"
    prepared = llm._build_structured_request("sys", canary, Answer, "local-model")
    measured = input_size(prepared.kwargs)
    build = Mock(wraps=llm._build_structured_request)
    log = Mock()
    monkeypatch.setattr(llm, "_build_structured_request", build)
    monkeypatch.setattr(llm, "_log_structured_request", log)
    seen = mock_http(monkeypatch, unexpected)
    with pytest.raises(ValueError) as caught:
        await llm.aexecute_complex_task(
            "sys",
            canary,
            Answer,
            "local-model",
            max_input_chars=measured - 1,
            single_attempt=single_attempt,
        )
    assert build.call_count == 1 and not log.called and seen == []
    assert str(measured) in str(caught.value) and str(measured - 1) in str(caught.value)
    assert canary not in str(caught.value)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, "64000"])
async def test_explicit_budget_requires_a_strict_positive_integer(monkeypatch, limit):
    async def unexpected(_request):
        raise AssertionError("An invalid budget must not send a request.")

    llm = router(monkeypatch)
    seen = mock_http(monkeypatch, unexpected)
    with pytest.raises(ValueError, match="positive integer"):
        await llm.aexecute_complex_task("sys", "hi", Answer, "local-model", max_input_chars=limit)
    assert seen == []


async def test_budget_none_retains_the_existing_unbounded_entry(monkeypatch):
    async def respond(request):
        return httpx.Response(200, json=completion(), request=request)

    seen = mock_http(monkeypatch, respond)
    result = await router(monkeypatch).aexecute_complex_task(
        "sys", "hi", Answer, "local-model", max_input_chars=None
    )
    assert result == Answer(value=7) and len(seen) == 1


def test_budget_counts_all_harness_contract_fields_and_ignores_transport_options():
    from backend.core.llm_structured_execution import require_input_budget

    kwargs = {
        "messages": [{"role": "user", "content": "明日"}],
        "tools": [{"type": "function", "function": {"name": "known", "parameters": {}}}],
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
        "model": "not part of input accounting",
        "max_tokens": 100,
    }
    measured = input_size(kwargs)
    require_input_budget(kwargs, measured)
    with pytest.raises(ValueError):
        require_input_budget(kwargs, measured - 1)


async def test_explicit_budget_also_admits_the_prepared_legacy_blank_retry(monkeypatch):
    async def respond(request):
        return httpx.Response(
            200, json=completion("", reasoning="Unfinished reasoning."), request=request
        )

    llm = router(monkeypatch)
    measured = input_size(llm._build_structured_request("sys", "hi", Answer, "local-model").kwargs)
    seen = mock_http(monkeypatch, respond)
    with pytest.raises(ValueError, match="input exceeds"):
        await llm.aexecute_complex_task(
            "sys", "hi", Answer, "local-model", max_input_chars=measured
        )
    assert len(seen) == 1
