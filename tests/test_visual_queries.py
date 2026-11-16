"""Private per-image query capture is isolated and independent of raw debug logging."""

import asyncio

import pytest

from backend.core import llm_logger
from backend.core.visual_queries import capture_query, collect_queries
from tests.test_scene_illustrations import illustration_world

__all__ = ["illustration_world"]


def test_raw_llm_reply_is_captured_without_enabling_telemetry(monkeypatch):
    monkeypatch.setattr(llm_logger, "_TELEMETRY_ENABLED", False)
    with collect_queries() as queries:
        llm_logger.log_llm_interaction(
            "local-model",
            "custom_openai",
            "Describe the visible scene.",
            "A nurse at a window.",
            "normalized response",
            raw_response={"choices": [{"message": {"content": "Original response"}}]},
            operation="visible_frame",
        )
    assert queries == [
        {
            "system_prompt": "Describe the visible scene.",
            "user_prompt": "A nurse at a window.",
            "response": "Original response",
            "model": "local-model",
            "operation": "Scene analysis",
            "truncated": False,
        }
    ]
    capture_query("outside", "outside", "outside", "model")
    assert len(queries) == 1


@pytest.mark.asyncio
async def test_parallel_generations_cannot_share_queries():
    async def run(text):
        with collect_queries() as queries:
            await asyncio.sleep(0)
            capture_query("system", text, text, "model")
        return queries

    first, second = await asyncio.gather(run("first"), run("second"))
    assert first[0]["user_prompt"] == "first"
    assert second[0]["user_prompt"] == "second"


def test_capture_is_bounded_and_failure_resets_context():
    with pytest.raises(ValueError), collect_queries() as queries:
        for _ in range(10):
            capture_query("s" * 33000, "user", "response", "model")
        raise ValueError("generation failed")
    assert len(queries) == 4
    assert queries[0]["truncated"] is True
    assert len(queries[0]["system_prompt"]) == 32000
    capture_query("outside", "outside", "outside", "model")
    assert len(queries) == 4


@pytest.mark.asyncio
async def test_queries_are_saved_with_image_and_returned_after_reload(
    auth_client, illustration_world, monkeypatch
):
    from backend.engine.scene_illustrations import render
    from tests.test_scene_illustrations import finish

    async def adapt(description, rules, user, **kwargs):
        capture_query("Use visible facts.", description, "A quiet cafe.", "local-model")
        return "A quiet cafe."

    monkeypatch.setattr(render, "adapt_body", adapt)
    result = await finish(auth_client)
    assert result["state"] == "succeeded"
    saved = result["result"]["generation_details"]["queries"]
    assert saved[0]["response"] == "A quiet cafe."
    response = await auth_client.get(
        "/api/adventures/moment/illustrations", params={"message_id": "moment-reply"}
    )
    assert response.status_code == 200
    assert response.json()["generation_details"]["queries"] == saved
