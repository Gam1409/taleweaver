"""Provider usage remains optional, task-scoped and independent of file logging."""

import asyncio

from backend.core import llm_logger
from backend.core.llm_usage_capture import capture_usage, record_usage


def test_disabled_logging_still_captures_real_counts_without_prompts(monkeypatch):
    monkeypatch.setattr(llm_logger, "_TELEMETRY_ENABLED", False)
    with capture_usage() as records:
        llm_logger.log_llm_interaction(
            "model",
            "provider",
            "PRIVATE PROMPT",
            "input",
            "reply",
            {"usage": {"prompt_tokens": 42, "completion_tokens": 7}},
        )
    assert records == [{"prompt_tokens": 42, "completion_tokens": 7}]
    record_usage({"prompt_tokens": 999})
    assert len(records) == 1


def test_unknown_and_malformed_counts_are_not_zero_or_estimates():
    with capture_usage() as records:
        record_usage(None)
        record_usage({"prompt_tokens": "10", "completion_tokens": True})
        record_usage({"prompt_tokens": -1, "completion_tokens": 0})
    assert records == [
        {"prompt_tokens": None, "completion_tokens": None},
        {"prompt_tokens": None, "completion_tokens": None},
        {"prompt_tokens": None, "completion_tokens": 0},
    ]


async def test_parallel_and_nested_captures_are_isolated():
    async def task(count):
        with capture_usage() as outer:
            await asyncio.sleep(0)
            with capture_usage() as inner:
                record_usage({"prompt_tokens": count + 1})
            record_usage({"prompt_tokens": count})
        return outer, inner

    first, second = await asyncio.gather(task(10), task(20))
    assert first[0][0]["prompt_tokens"] == 10 and first[1][0]["prompt_tokens"] == 11
    assert second[0][0]["prompt_tokens"] == 20 and second[1][0]["prompt_tokens"] == 21
