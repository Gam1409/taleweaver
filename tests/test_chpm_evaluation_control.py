"""Counterexample probes report weak semantic review instead of certifying control."""

import json

import pytest

from backend.engine.chpm.evaluation import control
from backend.engine.chpm.evaluation.cases import choose
from backend.engine.chpm.evaluation.runner import run_arm
from tests.test_chpm_evaluation import Models, settings


class ControlModels(Models):
    async def call(self, system, content, model, **kwargs):
        payload = json.loads(content)
        if kwargs["phase"] == "validation" and not self.reject:
            self.requests.append(("validation", system, payload))
            # Deliberately permissive review: the tool must expose its false acceptance.
            return json.dumps(
                {"matches": True, "evidence": [{"actor_id": "npc", "passage_id": "p0"}]}
            )
        return await super().call(system, content, model, **kwargs)


@pytest.mark.parametrize("reject", [0, 1, 2])
@pytest.mark.parametrize("violation", ["takeover", "promise", "completed_action"])
async def test_probe_distinguishes_false_acceptance_repair_and_failed_repair(reject, violation):
    case = choose(["continue-ru"])[0]
    source = await run_arm(case, 1, "chpm", Models(), settings())
    models = ControlModels(reject=reject)
    result = await control.probe(case, source, models, settings(), violation_kind=violation)
    assert result["injected_text_would_be_published"] is (reject == 0)
    assert result["repair_accepted"] is (reject == 1)
    assert bool(result["error_type"]) is (reject == 2)
    assert len(result["calls"]) == (1 if reject == 0 else 3)
    assert "not proof of universal control" in control.markdown(result)
    assert source.response != result["injected_narration"]
    assert result["violation_kind"] == violation
    if violation != "takeover":
        assert result["injected_narration"].startswith(source.response)
    assert case.rubric not in str(models.requests)


async def test_probe_requires_a_successful_controlled_source():
    case = choose(["continue-ru"])[0]
    source = await run_arm(case, 1, "baseline", Models(), settings())
    with pytest.raises(ValueError, match="accepted CHPM reply"):
        await control.probe(case, source, Models(), settings())
