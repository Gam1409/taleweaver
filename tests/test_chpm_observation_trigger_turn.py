"""The real VN transaction carries stable state grounds through quiet dialogue and copies."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import host_sources, inference, rendering
from backend.engine.chpm.state import load
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import configured, run
from tests.test_chpm_physical_continuity_turn import manually
from tests.test_chpm_turn import ChpmRoles
from tests.test_physical_conditions import record
from tests.test_vn_turn_integration import install_roles


class StateFeelingRoles(ChpmRoles):
    async def simple(self, system, payload, model, **kwargs):
        raw = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") != "proposal":
            return raw
        supplied = json.loads(payload)
        observed = next(
            row
            for row in supplied["appraisal_context"]["visible_evidence"]
            if row.get("currently_observed") and "CURRENT_NECK_PAIN" in row["text"]
        )
        body = json.loads(raw)
        body["experiences"] = (
            []
            if observed.get("already_supports_states")
            else [
                {
                    "channel": "affect",
                    "dimension": "fear",
                    "about_id": None,
                    "level": "moderate",
                    "personal_motive_ids": ["character"],
                    "citations": [
                        {"source_id": observed["source_id"], "quote": "CURRENT_NECK_PAIN"}
                    ],
                    "explanation": "The current pain makes it harder to remain composed.",
                    "alternatives": ["May still concentrate on practical conversation"],
                    "unknowns": [],
                }
            ]
        )
        return json.dumps(body)


@pytest.mark.parametrize("reject", [False, True])
async def test_state_appraisal_commits_only_with_review_and_survives_quiet_turns(
    monkeypatch, reject
):
    roles = StateFeelingRoles(reject=reject)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        manually(state, [record(target_id="LINA", detail="CURRENT_NECK_PAIN")], "known-injury")
        await db.commit()
        before = await capture(db, state.session_id)
        manager, chunks = await run(db, user, "Let's discuss the weather.")
        if reject:
            assert not any(chunk.startswith("event: final") for chunk in chunks)
            assert not load(manager.state).minds
            return
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        first = load(manager.state).minds["LINA"]
        assert len(first.snapshot.experiences) == 1
        assert len([s for s in first.sources.values() if s.kind == "host_observation"]) == 1
        manager, chunks = await run(db, user, "We continue the quiet conversation.")
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        second = load(manager.state).minds["LINA"]
        assert second.snapshot.experiences == first.snapshot.experiences
        assert len([s for s in second.sources.values() if s.kind == "host_observation"]) == 1
        assert roles.chpm_calls == ["perception", "proposal", "validation"] * 2
        assert "current pain" in str(roles.proposal_inputs[-1]["experience_context"])
        bundle = await SessionExporter.export_ads(db, manager.game_id)
        copied_id = await SessionImporter.import_ads(db, bundle, user.id)
        assert copied_id
        copied_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == copied_id)
        )
        copied = load(copied_state).minds["LINA"]
        assert (
            await host_sources.reconcile(SimpleNamespace(db=db, game_id=copied_id), copied)
            == copied
        )
        assert copied.snapshot.experiences[0].level == "moderate"
        await restore(db, manager.game_id, before)
        await db.refresh(manager.state)
        assert not load(manager.state).minds
