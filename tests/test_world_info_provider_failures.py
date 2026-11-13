"""Inference availability is not malformed source output and must not trigger correction."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.core.llm_router import GameMasterLLM
from backend.engine.world_info import jobs, queue, worker
from backend.engine.world_info.extraction_contracts import ExtractionProposal
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_world_info_extraction import proposal
from tests.test_world_info_jobs import portrait_world, seed_revision, world_info_owner

__all__ = ["portrait_world", "world_info_owner"]


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (InferenceQueueError, "inference_waiting"),
        (InferenceUncertainError, "inference_waiting"),
        (TimeoutError, "timeout"),
        (ConnectionError, "processing_failed"),
        (ValueError, "processing_failed"),
    ],
)
async def test_actual_extractor_preserves_operational_failure_without_correction(
    world_info_owner, monkeypatch, caplog, failure, expected_code
):
    revision_id = await seed_revision(world_info_owner)
    router = SimpleNamespace(
        max_tokens=6144,
        model="fictional-extraction-model",
        aexecute_complex_task=AsyncMock(
            side_effect=failure("fictional provider diagnostic sentinel")
        ),
    )
    monkeypatch.setattr(
        "backend.engine.world_info.extraction.GameMasterLLM.for_role", lambda *_args: router
    )
    claim = await queue.claim_next("portrait-session", world_info_owner)
    await worker.process_claim(claim)
    assert router.aexecute_complex_task.await_count == 1
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert (row.status, row.cursor, row.attempts, row.last_error_code) == (
            "failed",
            0,
            1,
            expected_code,
        )
    assert "diagnostic sentinel" not in caplog.text


@pytest.mark.parametrize(
    "failure,expected_code",
    [
        (InferenceQueueError, "inference_waiting"),
        (InferenceUncertainError, "inference_waiting"),
        (TimeoutError, "timeout"),
        (ValueError, "processing_failed"),
    ],
)
async def test_real_router_transport_failure_never_becomes_an_output_correction(
    world_info_owner, monkeypatch, caplog, failure, expected_code
):
    revision_id = await seed_revision(world_info_owner)
    transport = AsyncMock(side_effect=failure("fictional transport diagnostic sentinel"))
    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", transport)
    logical = []
    original = GameMasterLLM.aexecute_complex_task

    async def execute(self, *args, **kwargs):
        logical.append(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(GameMasterLLM, "aexecute_complex_task", execute)
    claim = await queue.claim_next("portrait-session", world_info_owner)
    await worker.process_claim(claim)
    assert len(logical) == transport.await_count == 1
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert (row.status, row.cursor, row.attempts, row.last_error_code) == (
            "failed",
            0,
            1,
            expected_code,
        )
    assert "diagnostic sentinel" not in caplog.text


async def test_real_router_completed_invalid_json_still_gets_one_bounded_correction(
    world_info_owner, monkeypatch
):
    revision_id = await seed_revision(
        world_info_owner, content="The lighthouse overlooks the harbour."
    )

    def response(content):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")
            ],
            model_dump=lambda: {},
        )

    transport = AsyncMock(side_effect=[response("null"), response(json.dumps(proposal()))])
    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", transport)
    claim = await queue.claim_next("portrait-session", world_info_owner)
    await worker.process_claim(claim)
    assert transport.await_count == 2
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert (row.status, row.cursor, row.attempts, row.facts_count) == ("review", 1, 2, 1)


async def test_invalid_generator_settings_after_queueing_do_not_leave_unresumable_queued_work(
    world_info_owner,
):
    revision_id = await seed_revision(world_info_owner)
    async with TestSessionLocal() as db:
        user = await db.get(User, world_info_owner)
        user.llm_settings = {"generator_model_provider": "ollama", "generator_model": ""}
        await db.commit()
    worker.schedule("portrait-session", world_info_owner)
    task = worker._tasks["portrait-session"]
    await asyncio.gather(task, return_exceptions=True)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert (row.status, row.last_error_code, row.attempts) == ("failed", "processing_failed", 0)


async def test_config_failure_does_not_strand_other_jobs_and_resume_keeps_completed_batch(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    async with TestSessionLocal() as db:
        valid_settings = deepcopy((await db.get(User, owner)).llm_settings)
    text = "".join(
        f"Archive custom {index:04}: keep documents inside the numbered drawer.\n"
        for index in range(280)
    )
    first_id = await seed_revision(owner, content=text)
    second_id = await seed_revision(owner, content="Another archive rule is documented.")
    calls = []

    async def transport(self, kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        quote = payload["passages"][0]["text"][:80]
        calls.append(quote)
        if len(calls) == 1:
            async with TestSessionLocal() as db:
                user = await db.get(User, owner)
                user.llm_settings = {"generator_model_provider": "ollama", "generator_model": ""}
                await db.commit()
        result = proposal(quote)
        result["facts"][0]["evidence"][0]["passage_id"] = payload["passages"][0]["id"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(result)), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", transport)
    await worker._run("portrait-session", owner)
    async with TestSessionLocal() as db:
        first = await db.get(WorldInfoRevision, first_id)
        second = await db.get(WorldInfoRevision, second_id)
        assert (first.status, first.cursor, first.entries_count, first.attempts) == (
            "failed",
            1,
            1,
            1,
        )
        assert (second.status, second.cursor, second.attempts) == ("failed", 0, 0)
        assert first.last_error_code == second.last_error_code == "processing_failed"
        user = await db.get(User, owner)
        user.llm_settings = valid_settings
        await db.commit()
        await jobs.start_processing(db, owner, "portrait-session", first_id, first.control_version)
        await db.commit()
    assert len(calls) == 1
    await worker._run("portrait-session", owner)
    async with TestSessionLocal() as db:
        first = await db.get(WorldInfoRevision, first_id)
        second = await db.get(WorldInfoRevision, second_id)
        assert first.status == "review" and first.cursor == first.total_batches
        assert (
            first.entries_count
            == first.facts_count
            == first.attempts
            == len(calls)
            == first.total_batches
        )
        assert first.processing_language == "Russian"
        assert second.status == "failed" and second.attempts == 0


@pytest.mark.parametrize("synchronous", [False, True])
async def test_actual_router_sdk_retries_keep_category_but_never_log_provider_body(
    world_info_owner, monkeypatch, caplog, synchronous
):
    async with TestSessionLocal() as db:
        user = await db.get(User, world_info_owner)
    router = GameMasterLLM.for_role(user, "generator")
    error = TimeoutError("fictional private source and provider body sentinel")
    asynchronous = AsyncMock(side_effect=error)
    synchronous_sdk = Mock(side_effect=error)
    monkeypatch.setattr(
        GameMasterLLM,
        "_get_litellm",
        classmethod(
            lambda cls: SimpleNamespace(acompletion=asynchronous, completion=synchronous_sdk)
        ),
    )
    monkeypatch.setattr("backend.core.llm_logger._TELEMETRY_ENABLED", False)
    monkeypatch.setattr("backend.core.inference.transport.target", lambda *_: None)
    monkeypatch.setattr("backend.core.llm_router.target", lambda *_: None)
    monkeypatch.setattr("backend.core.llm_router.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("backend.core.llm_router.time.sleep", lambda *_: None)
    with pytest.raises(TimeoutError):
        if synchronous:
            router.execute_complex_task(
                "Extract source data.", "Fictional source.", ExtractionProposal, router.model
            )
        else:
            await router.aexecute_complex_task(
                "Extract source data.", "Fictional source.", ExtractionProposal, router.model
            )
    assert (synchronous_sdk.call_count if synchronous else asynchronous.await_count) == 4
    assert "TimeoutError" in caplog.text and "retry 3/3" in caplog.text
    assert f"provider={router.provider} role={router.model_category}" in caplog.text
    assert "private source and provider body sentinel" not in caplog.text
