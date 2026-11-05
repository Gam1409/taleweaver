"""Offline stress of the same ports used by the opt-in live matrix."""

import json

import pytest

from backend.engine.chpm.evaluation import matrix_cases, matrix_cli, matrix_runner
from tests.chpm_projection_fixture import public_projection
from tests.test_chpm_kernel import grounded_proposal


class Models:
    model = "mock"
    provider = "mock"
    max_tokens = 8192
    request_timeout = 30
    enable_thinking = False

    def __init__(self, fault=None):
        self.fault = fault
        self.active = []

    def __call__(self, _role):
        return self

    async def aexecute_simple_task(self, _system, content, _model, **kwargs):
        phase = kwargs["phase"]
        body = json.loads(content)
        if self.fault == phase:
            return '{"broken":'
        if phase == "perception":
            return json.dumps(public_projection(body))
        if phase == "proposal":
            self.active.append(body["actor_id"])
            value = grounded_proposal().model_dump()
            value["candidates"]["CONTINUE"]["goal_quote"] = body["authored_goal"]
            return json.dumps(value)
        if phase in {"narration", "repair"}:
            return "\n".join(f"Person {key[-2:]}: I will check my part." for key in self.active)
        if phase == "validation":
            if self.fault == "reject_twice":
                return json.dumps({"matches": False, "issues": ["Intent does not match"]})
            return json.dumps(
                {
                    "matches": True,
                    "evidence": [
                        {
                            "actor_id": key,
                            "passage_id": next(
                                p
                                for p, text in body["passages"].items()
                                if f"Person {key[-2:]}:" in text
                            ),
                        }
                        for key in body["controlled_actor_ids"]
                    ],
                }
            )
        raise AssertionError(phase)


def case(population=20, history=40):
    return matrix_cases.MatrixCase(
        "offline", "fantasy", "conflict", population, history, min(3, population), history == 40
    )


def test_manifest_has_full_traits_diverse_worlds_counts_histories_and_no_calls():
    all_cases = matrix_cases.catalogue()
    assert len(all_cases) == len({c.id for c in all_cases}) == 360
    assert {c.population for c in all_cases} == {1, 3, 5, 10, 20}
    assert {c.history_turns for c in all_cases} == {0, 12, 40}
    for actor in matrix_cases.actors(case()):
        assert set(actor.metadata_json["personality_profile"]) == set(matrix_cases.FIELDS)
        assert all(actor.metadata_json["personality_profile"].values())
    assert matrix_cli.manifest([case()], all_present=True)["max_logical_calls"] == 26


def test_situations_reach_cognition_and_do_not_assert_private_feelings():
    variants = [
        matrix_cases.MatrixCase("test", "everyday", situation, 1, 0, 1, False)
        for situation in matrix_cases.SITUATIONS
    ]
    assert len({item.message for item in variants}) == len(variants)
    fear = next(item for item in variants if item.situation == "fear")
    assert "audible crash" in fear.observed_event
    assert "fear" not in fear.observed_event
    attraction = next(item for item in variants if item.situation == "attraction")
    assert not attraction.observed_event


@pytest.mark.parametrize(
    "population,history,all_present",
    [(1, 0, False), (5, 12, False), (20, 40, False), (20, 40, True)],
)
async def test_reviewed_matrix_commits_only_active_minds(population, history, all_present):
    result = await matrix_runner.run(case(population, history), Models(), all_present=all_present)
    assert result["status"] == "ok", result["error"]
    assert result["identity_unchanged"] and result["inactive_unchanged"]
    assert len(result["active"]) == (population if all_present or population <= 3 else 1)
    assert len(result["calls"]) == len(result["active"]) + 3
    assert all(
        value["semantic_distinctness"] == "manual review required"
        for value in result["candidate_distinctness"].values()
    )


@pytest.mark.parametrize("fault", ["perception", "proposal", "validation", "reject_twice"])
async def test_broken_json_and_failed_repairs_never_publish_or_commit(fault):
    result = await matrix_runner.run(case(3, 12), Models(fault))
    assert result["status"] == "failed"
    assert result["response"] == ""
    assert result["failed_turn_unchanged"]
    assert result["identity_unchanged"]
    assert len(result["calls"]) <= 8
