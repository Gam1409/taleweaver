"""Real VN publication/rollback boundaries with proposed beliefs from a mock model."""

import json

import pytest

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import configured, run
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import install_roles


class AppraisalRoles(ChpmRoles):
    def __init__(self):
        super().__init__()
        self.invalid = False
        self.invalid_motive = False

    async def simple(self, system, payload, model, **kwargs):
        result = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") != "proposal":
            return result
        supplied = json.loads(payload)
        context = supplied["appraisal_context"]
        visible = [e for e in context["visible_evidence"] if e["speaker_id"] == "@player"][-1]
        existing = context["existing_beliefs"]
        proposed = {
            "about_id": "@player",
            "domain": "reliability",
            "statement": "May fail to keep a promise",
            "stance": "support",
            "citations": [{"source_id": visible["source_id"], "quote": visible["text"]}],
            "alternatives": ["External circumstances may explain it"],
            "unknowns": ["Intent and ability to act"],
        }
        if existing:
            proposed.update(belief_id=existing[0]["belief_id"], stance="challenge")
            for field in ("about_id", "domain", "statement"):
                proposed.pop(field)
        if self.invalid:
            proposed["citations"][0]["quote"] = "NEVER_SAID_THIS"
        body = json.loads(result)
        body["interpretations"] = [proposed]
        if self.invalid_motive:
            body["candidates"]["DEFER"]["motives"][0]["motive_id"] = "another-npc-secret"
        return json.dumps(body)


def install(monkeypatch):
    roles = AppraisalRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    return roles


async def test_interpretations_reach_narrator_and_commit_with_reply_without_extra_calls(
    monkeypatch,
):
    roles = install(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        manager, chunks = await run(db, user, "Я не выполнил обещание.")
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        first = load(state)
        decision = first.actors["LINA"]
        mind = first.minds["LINA"]
        assert len(decision.interpretation_ids) == 1
        assert decision.interpretation_ids[0] in {e.id for e in mind.snapshot.evidence}
        assert mind.snapshot.beliefs[0].probability is None
        assert "May fail to keep a promise" in str(roles.prompts[-1])
        assert decision.motivation_policy == "source-grounded-v1"
        assert set(decision.candidate_motives) == {"CONTINUE", "DEFER"}
        assert "selected_motives_not_world_facts" in str(roles.prompts[-1])
        assert (
            decision.candidate_motives["CONTINUE"][0].source.text
            == mind.genesis.identity.authored_goals[0]
        )
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
        manager, chunks = await run(db, user, "Меня задержала авария, могу показать справку.")
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        updated = load(manager.state).minds["LINA"]
        assert updated.snapshot.beliefs[0].status == "challenged"
        assert updated.snapshot.beliefs[0].revision == 2
        assert updated.genesis == mind.genesis


@pytest.mark.parametrize("failure", ["invalid_citation", "invalid_motive", "rejected_narration"])
async def test_failed_turn_never_commits_proposed_beliefs(monkeypatch, failure):
    roles = install(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        await run(db, user, "Я не выполнил обещание.")
        before = load(state)
        roles.invalid = failure == "invalid_citation"
        roles.invalid_motive = failure == "invalid_motive"
        roles.reject = failure == "rejected_narration"
        _, chunks = await run(db, user, "Причина была другой.")
        assert any(c.startswith("event: error") for c in chunks)
        assert not any(c.startswith("event: chunk") for c in chunks)
        await db.refresh(state)
        assert load(state) == before
