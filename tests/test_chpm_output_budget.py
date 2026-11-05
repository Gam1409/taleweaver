"""Truncated structured responses fail without spending an identical retry."""

import asyncio
from dataclasses import asdict

import pytest

from backend.core import llm_logger
from backend.core.llm_completion_capture import capture_completions, record_completion
from backend.engine.chpm import inference
from backend.engine.chpm.evaluation import matrix_runner
from tests.test_chpm_matrix import Models, case


def response(reason="length", count=2048):
    return {"choices": [{"finish_reason": reason}], "usage": {"completion_tokens": count}}


class LimitedModel(Models):
    def __init__(self, reason="length", count=2048, text='{"cut":'):
        super().__init__()
        self.reason, self.count, self.text = reason, count, text

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        if kwargs["phase"] == "proposal":
            record_completion(response(self.reason, self.count))
            return self.text
        return await super().aexecute_simple_task(system, content, model, **kwargs)


@pytest.mark.parametrize("reason", ["length", "max_tokens", None])
async def test_exhaustion_is_not_retried_and_does_not_commit(reason):
    result = await matrix_runner.run(case(1, 0), LimitedModel(reason))
    assert result["status"] == "failed"
    assert "exhausted its output budget (2048 tokens)" in result["error"]
    assert result["failed_turn_unchanged"] and result["identity_unchanged"]
    assert result["response"] == ""
    assert [c["phase"] for c in result["calls"]] == ["perception", "proposal"]
    assert result["calls"][-1]["finish_reason"] == reason
    assert result["calls"][-1]["output_limit"] == 2048


def test_explicit_length_rejects_even_parseable_text_but_missing_metadata_is_not_proof():
    with capture_completions() as records:
        record_completion(response())
    with pytest.raises(inference.OutputBudgetError):
        inference.check_output_budget(records, 2048, "proposal")
    inference.check_output_budget([], 2048, "proposal", invalid_json=True)
    inference.check_output_budget(records * 2, 2048, "proposal", invalid_json=True)


@pytest.mark.parametrize("reason,count", [("stop", 2048), (None, 2047), (None, None)])
def test_counts_alone_do_not_reject_a_complete_response(reason, count):
    with capture_completions() as records:
        record_completion(response(reason, count))
    inference.check_output_budget(records, 2048, "proposal")
    inference.check_output_budget(records, 2048, "proposal", invalid_json=True)


def test_metadata_recording_does_not_require_logging_or_retain_private_text(monkeypatch):
    monkeypatch.setattr(llm_logger, "_TELEMETRY_ENABLED", False)
    with capture_completions() as records:
        raw = response()
        raw["choices"][0]["message"] = {"content": "PRIVATE"}
        llm_logger.log_llm_interaction("model", "provider", "SECRET", "input", "reply", raw)
    assert [asdict(r) for r in records] == [{"finish_reason": "length", "completion_tokens": 2048}]
    record_completion(response())
    assert len(records) == 1


def test_ambiguous_choices_and_invalid_provider_values_cannot_prove_exhaustion():
    with capture_completions() as records:
        record_completion({"choices": [{}, {}], "usage": {"completion_tokens": 99999}})
        record_completion(response("untrusted provider text", True))
    assert all(r.finish_reason is None and r.completion_tokens is None for r in records)


async def test_schema_failure_at_cap_without_length_is_still_repairable():
    result = await matrix_runner.run(case(1, 0), LimitedModel(None, text='{"not_a_draft":true}'))
    assert "exhausted its output budget" not in result["error"]
    assert "proposal_repair" in [c["phase"] for c in result["calls"]]


async def test_nested_capture_fans_out_but_independent_tasks_do_not_mix():
    async def task(count):
        with capture_completions() as outer:
            await asyncio.sleep(0)
            with capture_completions() as inner:
                record_completion(response(count=count))
        return outer, inner

    first, second = await asyncio.gather(task(10), task(20))
    assert first[0] == first[1] and first[0][0].completion_tokens == 10
    assert second[0] == second[1] and second[0][0].completion_tokens == 20


async def test_explicit_evaluation_override_reaches_model_and_is_validated_before_inference():
    model = LimitedModel(count=4096)
    result = await matrix_runner.run(case(1, 0), model, max_output_tokens=4096)
    assert "4096 tokens" in result["error"]
    assert model.max_tokens == 4096
    with pytest.raises(ValueError):
        await matrix_runner.run(case(1, 0), Models(), max_output_tokens=9000)
