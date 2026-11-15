"""Opt-in evaluation captures admitted experience, never an entire private notebook."""

import json

import pytest

from backend.engine.chpm.evaluation.port import MeasuredFactory


class Model:
    model = "mock"
    provider = "mock"
    max_tokens = 1200
    request_timeout = 10

    async def aexecute_simple_task(self, *_args, **_kwargs):
        return "{}"


@pytest.mark.parametrize("phase", ["proposal", "proposal_repair"])
async def test_proposal_audit_retains_experience_and_packing_without_private_notes(phase):
    experience = {
        "states": [{"state_id": "x1", "last_assessed_reason": "The promise is unresolved."}],
        "omitted": 2,
        "omitted_reasons": 1,
    }
    body = {
        "actor_id": "npc",
        "experience_context": experience,
        "appraisal_context": {"visible_evidence": []},
        "context_packing": {"canonical_history_changed": False},
        "private_notebook_not_world_facts": {"secret": "not for this audit"},
    }
    factory = MeasuredFactory(lambda _role: Model(), limit=1)

    await factory("complex").aexecute_simple_task("policy", json.dumps(body), "mock", phase=phase)

    assert len(factory.calls) == 1
    audit = factory.calls[0].context_audit
    assert audit["experience_context"] == experience
    assert audit["appraisal_context"] == body["appraisal_context"]
    assert audit["context_packing"] == body["context_packing"]
    assert "private_notebook_not_world_facts" not in audit
    assert "not for this audit" not in json.dumps(audit)
