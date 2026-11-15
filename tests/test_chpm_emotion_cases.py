"""The optional emotion suite exercises production ports without grading mock prose."""

import json
from collections import defaultdict

import pytest

from backend.engine.chpm.evaluation import emotion_cases, matrix_cases, matrix_cli, matrix_runner
from backend.engine.chpm.evaluation.matrix_history import seed
from backend.engine.chpm.identity_adapter import from_actor
from tests.test_chpm_matrix import Models


def test_emotion_plan_contains_twelve_matched_pairs_with_explicit_languages_and_cost():
    cases = matrix_cases.choose("emotion", [])
    assert len(cases) == len({case.id for case in cases}) == 24
    groups = defaultdict(list)
    for case in cases:
        groups[(case.pair, case.language_code)].append(case)
    assert len(groups) == 12
    for pair in groups.values():
        left, right = pair
        assert left.message == right.message
        assert left.population == right.population
        assert left.language == right.language
        assert [from_actor(actor) for actor in matrix_cases.actors(left)] == [
            from_actor(actor) for actor in matrix_cases.actors(right)
        ]
    plan = matrix_cli.manifest(cases)
    assert plan["max_logical_calls"] == 176
    assert len(plan["case_rubrics"]) == 24
    assert "not model-generated" in plan["history"]
    assert matrix_cases.choose("emotion", [cases[-1].id]) == [cases[-1]]
    with pytest.raises(ValueError, match="unique case IDs"):
        matrix_cases.choose("emotion", ["not-an-emotion-case"])


def test_authored_detour_retains_the_original_report_without_forging_experience():
    variants = [case for case in emotion_cases.catalogue() if case.pair == "detour"]
    assert {case.history_turns for case in variants} == {1, 40}
    for case in variants:
        actor = matrix_cases.actors(case)[0]
        value = seed(case, actor, "synthetic-history")
        reports = [source for source in value.sources.values() if source.kind == "speech"]
        assert len(reports) == case.history_turns
        assert reports[0].text == case.history_text(0, actor.id)
        assert value.snapshot.experiences == ()
        assert all(not source.facts for source in reports)
        assert case.observed_event == ""


@pytest.mark.parametrize("fixture", emotion_cases.catalogue(), ids=lambda case: case.id)
async def test_emotion_fixtures_use_current_reviewed_path_with_no_quality_claim(fixture):
    result = await matrix_runner.run(fixture, Models())
    assert result["status"] == "ok", result["error"]
    assert result["identity_unchanged"] and result["inactive_unchanged"]
    assert result["psychological_quality"].startswith("unrated")
    proposals = [call for call in result["calls"] if call["phase"] == "proposal"]
    assert proposals
    assert all("experience_context" in call["context_audit"] for call in proposals)
    assert len(result["calls"]) <= fixture.active + 6


@pytest.mark.parametrize("language", ["English", "Russian"])
async def test_requested_language_reaches_actual_narration_payload(language):
    class RecordingModels(Models):
        async def aexecute_simple_task(self, system, content, model, **kwargs):
            if kwargs["phase"] == "narration":
                self.narration_payload = json.loads(content)
            return await super().aexecute_simple_task(system, content, model, **kwargs)

    fixture = next(case for case in emotion_cases.catalogue() if case.language == language)
    models = RecordingModels()
    result = await matrix_runner.run(fixture, models)
    assert result["status"] == "ok", result["error"]
    assert models.narration_payload["language"] == language
    assert models.narration_payload["player_message_untrusted"] == fixture.message
