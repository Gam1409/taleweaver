"""Subjective states commit only alongside reviewed live narration, with no new call."""

import json

import pytest

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_appraisal_turn import AppraisalRoles
from tests.test_chpm_host_turn import configured, run
from tests.test_vn_turn_integration import install_roles


class ExperienceRoles(AppraisalRoles):
    async def simple(self, system, payload, model, **kwargs):
        result = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") != "proposal":
            return result
        supplied = json.loads(payload)
        visible = [
            item
            for item in supplied["appraisal_context"]["visible_evidence"]
            if item["speaker_id"] == "@player"
        ][-1]
        body = json.loads(result)
        body["experiences"] = [
            {
                "channel": "need_frustration",
                "dimension": "autonomy",
                "about_id": None,
                "level": "moderate",
                "personal_motive_ids": ["character"],
                "citations": [{"source_id": visible["source_id"], "quote": visible["text"]}],
                "explanation": "Demand may conflict with personal agency",
                "alternatives": ["A misunderstanding"],
                "unknowns": ["Intent behind the request"],
            }
        ]
        return json.dumps(body)


@pytest.mark.parametrize("reject", [False, True])
async def test_experience_and_motive_policy_share_the_reviewed_turn_transaction(
    monkeypatch, reject
):
    roles = ExperienceRoles()
    roles.reject = reject
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        before = load(state)
        manager, chunks = await run(db, user, "Я хочу, чтобы ты согласилась со всем без вопросов.")
        if reject:
            assert not any(c.startswith("event: final") for c in chunks)
            assert load(manager.state).minds == before.minds
            return
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        assert any("Reviewing NPC reply..." in c for c in chunks)
        current = load(manager.state)
        decision = current.actors["LINA"]
        assert decision.policy_version == "motivated-choice-v2"
        assert len(decision.experience_ids) == 1
        assert current.minds["LINA"].snapshot.experiences[0].dimension == "autonomy"
        assert "subjective_experience_not_traits" in str(roles.prompts[-1])
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
