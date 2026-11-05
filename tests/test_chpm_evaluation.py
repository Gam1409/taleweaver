"""Evaluation executes production cognitive gates and keeps quality judgments human."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.llm_usage_capture import record_usage
from backend.engine.chpm.evaluation import cli, report, storage
from backend.engine.chpm.evaluation.cases import cases, choose
from backend.engine.chpm.evaluation.contracts import Rating
from backend.engine.chpm.evaluation.runner import run_arm
from backend.engine.chpm.schema import Settings
from tests.chpm_projection_fixture import public_projection
from tests.test_chpm_kernel import motivated_candidates, preferred_choice

SPEECH = "Let us start with the joints."


class Models:
    def __init__(self, reject=0, broken=None, with_usage=True):
        self.reject = reject
        self.broken = broken
        self.with_usage = with_usage
        self.requests = []

    def __call__(self, role):
        return SimpleNamespace(
            model="fake-model",
            provider="fake-provider",
            max_tokens=4096,
            request_timeout=10,
            aexecute_simple_task=self.call,
        )

    async def call(self, system, content, model, **kwargs):
        phase = kwargs["phase"]
        self.requests.append((phase, system, json.loads(content)))
        if phase == self.broken:
            raise RuntimeError("Provider secret must not appear in portable reports")
        if self.with_usage:
            record_usage({"prompt_tokens": 100, "completion_tokens": 20})
        if phase in {"narration", "repair"}:
            return SPEECH
        payload = json.loads(content)
        if phase == "perception":
            return json.dumps(public_projection(payload))
        if phase == "proposal":
            return json.dumps(
                {
                    **(
                        {"interpretations": [], "choice": preferred_choice(payload)}
                        if "appraisal_context" in payload
                        else {"appraisal": "A natural continuation"}
                    ),
                    "candidates": motivated_candidates(
                        {
                            "CONTINUE": {
                                "intention": "Discuss the first inspection step",
                                "goal_alignment": "supports",
                                "goal_quote": payload["authored_goal"],
                                "reconsider_if": "Bridge is closed",
                            },
                            "DEFER": {"intention": "Wait", "reconsider_if": "Asked a question"},
                        },
                        enabled="motivation_context" in payload,
                    ),
                }
            )
        assert phase == "validation"
        if self.reject:
            self.reject -= 1
            return json.dumps(
                {"matches": False, "issues": ["Does not express the chosen intention"]}
            )
        reference = next(key for key, quote in payload["passages"].items() if SPEECH in quote)
        return json.dumps(
            {"matches": True, "evidence": [{"actor_id": "npc", "passage_id": reference}]}
        )


def settings(**changes):
    return Settings(mode="live", actor_ids=["npc"], **changes)


async def paired():
    case = choose(["continue-ru"])[0]
    return [await run_arm(case, 1, arm, Models(), settings()) for arm in ("baseline", "chpm")]


async def test_both_arms_share_inputs_and_baseline_is_not_a_strawman():
    case = choose(["continue-ru"])[0]
    baseline_models, chpm_models = Models(), Models()
    baseline = await run_arm(case, 1, "baseline", baseline_models, settings())
    chpm = await run_arm(case, 1, "chpm", chpm_models, settings())
    assert baseline.status == chpm.status == "ok"
    assert [call.phase for call in baseline.calls] == ["narration"]
    assert [call.phase for call in chpm.calls] == [
        "perception",
        "proposal",
        "narration",
        "validation",
    ]
    baseline_request = baseline_models.requests[0]
    chpm_request = chpm_models.requests[2]
    assert baseline_request[2] == chpm_request[2]
    assert chpm_request[1].startswith(baseline_request[1])
    assert baseline_request[2]["character"] == case.character
    assert baseline_request[2]["witnessed_history"] == [line.model_dump() for line in case.history]
    assert case.rubric not in str(baseline_models.requests + chpm_models.requests)
    assert sum(call.prompt_tokens for call in chpm.calls) == 400
    assert baseline.trace == {} and chpm.trace["decisions"]["npc"]["selected"]["kind"] == "CONTINUE"


@pytest.mark.parametrize("reject,success,expected", [(1, True, 6), (2, False, 6)])
async def test_production_repair_limit_and_no_failed_response_publication(
    reject, success, expected
):
    result = await run_arm(cases()[0], 1, "chpm", Models(reject=reject), settings())
    assert (result.status == "ok") is success
    assert len(result.calls) == expected
    assert sum(call.phase == "repair" for call in result.calls) == 1
    assert bool(result.response) is success


async def test_insufficient_repair_budget_and_missing_usage_are_visible():
    result = await run_arm(
        cases()[0], 1, "chpm", Models(reject=1, with_usage=False), settings(max_calls_per_turn=3)
    )
    assert result.status == "failed" and not result.response
    assert len(result.calls) == 4  # The narrator is outside the CHPM-specific limit.
    assert all(call.prompt_tokens is None for call in result.calls)
    text = report.summarize([result], [], "seed", planned=2)
    assert "Recorded arms: 1/2" in text and "total unknown" not in text
    assert "unknown" in text and "Failures" in text
    assert "pending human review" in text


async def test_raw_provider_errors_do_not_leak_and_cancel_is_not_an_npc_event():
    result = await run_arm(cases()[0], 1, "baseline", Models(broken="narration"), settings())
    assert result.status == "failed" and result.error_type == "RuntimeError"
    assert "secret" not in result.model_dump_json()

    class Cancelled(Models):
        async def call(self, *args, **kwargs):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_arm(cases()[0], 1, "chpm", Cancelled(), settings())


async def test_blind_export_hides_arm_metadata_and_rating_hashes_bind_responses():
    results = await paired()
    group = report.pairs(results, "seed")[results[0].pair_id]
    review = report.blind_document(results, cases(), "seed")
    assert "fake-model" not in review and "fake-provider" not in review
    assert "### A" in review and "### B" in review
    rating = report.template(results[0].pair_id, group)
    assert all(value is None for value in rating.voice.values())
    assert "pending human review" in report.summarize(results, [rating], "seed", 2)
    for dimension in report.DIMENSIONS:
        setattr(
            rating,
            dimension,
            {label: 4 if result.arm == "chpm" else 2 for label, result in group.items()},
        )
    rating.preferred = next(label for label, result in group.items() if result.arm == "chpm")
    text = report.summarize(results, [rating], "seed", 2)
    assert "CHPM 1" in text and "| voice | 2.00 | 4.00 | +2.00 |" in text
    assert "|---|---:|---:|---:|\n| voice" in text  # A valid Markdown table, without blank rows.
    results[0].response = "Changed after rating"
    with pytest.raises(ValueError, match="changed responses"):
        report.summarize(results, [rating], "seed", 2)


async def test_reject_duplicate_results_ratings_and_invalid_scores():
    results = await paired()
    with pytest.raises(ValueError, match="Duplicate result"):
        report.pairs(results + [results[0]], "seed")
    rating = report.template(results[0].pair_id, report.pairs(results, "seed")[results[0].pair_id])
    with pytest.raises(ValueError, match="Duplicate or unknown"):
        report.summarize(results, [rating, rating], "seed", 2)
    for values in ({"A": 5, "B": 1}, {"A": True, "B": 1}, {"A": 2}):
        raw = rating.model_dump()
        raw["voice"] = values
        with pytest.raises(ValidationError):
            Rating.model_validate(raw)


async def test_private_storage_and_no_overwrite_or_path_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ROOT", tmp_path / "private")
    case = choose(["continue-ru"])[0]
    manifest = {"cases": [case.model_dump()], "repeats": 1, "blind_seed": "seed"}
    folder = storage.create("test-run", manifest)
    with pytest.raises(FileExistsError):
        storage.create("test-run", manifest)
    for identifier in ("../escape", "/absolute", "x/y", "..", ""):
        with pytest.raises(ValueError):
            storage.directory(identifier)
    for result in await paired():
        storage.append(folder, result)
    storage.finish(folder)
    assert "pending human review" in storage.read(folder, "summary.md")
    assert storage.report(folder) == storage.read(folder, "summary.md")
    (folder / "escape").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="escapes"):
        storage.path(folder, "escape")


def test_plan_has_bounded_cost_and_bilingual_cases_without_model_calls(capsys):
    suite = cases()
    assert len(suite) == 41 and len({case.id for case in suite}) == 41
    assert {case.language for case in suite} == {"English", "Russian"}
    assert cli.main(["plan", "--case", "continue-ru", "--repeats", "3"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["max_logical_calls"] == 24
    with pytest.raises(ValueError):
        choose(["missing"])
    with pytest.raises(ValueError):
        choose(["continue-ru", "continue-ru"])


async def test_forty_turn_context_keeps_old_commitment_outside_transcript_window():
    case = choose(["long_history_40-ru"])[0]
    assert len(case.history) == 80 and case.agenda[0].history_index == 5
    models = Models()
    result = await run_arm(case, 1, "chpm", models, settings())
    assert result.status == "ok", result.error_detail
    proposal = next(payload for phase, _, payload in models.requests if phase == "proposal")
    assert len(proposal["witnessed_utterances_not_world_facts"]) == 12
    assert proposal["witnessed_utterances_not_world_facts"][0]["source_message_id"] == "history-68"
    assert proposal["declared_agenda_not_world_facts"][0]["text"] == case.agenda[0].text
    assert proposal["declared_agenda_not_world_facts"][0]["quote"] == case.history[5].text
    narrator = next(payload for phase, _, payload in models.requests if phase == "narration")
    assert len(narrator["witnessed_history"]) == 80


async def test_excessive_context_fails_before_narration_instead_of_silent_truncation():
    case = choose(["long_history_40-ru"])[0]
    case.history[0].text = "Huge story segment. " * 1000
    models = Models()
    result = await run_arm(case, 1, "baseline", models, settings(max_input_chars=8000))
    assert result.status == "failed"
    assert result.calls == [] and models.requests == []
