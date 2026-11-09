"""Pose deltas must stay evidence-backed, scene-local and separate from mechanics."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, _visible_facts
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, narration_block, project, reconcile
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

TEXT = "Hero sits on the bench. Лина stands in front of Hero."
CAST = [{"id": "hero", "name": "Hero"}, {"id": "LINA", "name": "Лина", "position": "garden"}]


def state():
    result = SimpleNamespace(
        current_scene_id="START", entity_states={"LINA": {"inventory": ["COAT"]}}
    )
    write_settings(result, VnSettings(scene_staging=True))
    return result


def extraction():
    return SceneExtraction.model_validate(
        {
            "changes": [
                {
                    "entity_id": "hero",
                    "posture": "sitting",
                    "evidence": "Hero sits on the bench.",
                    "placement": {
                        "relation": "on",
                        "target_kind": "scene_object",
                        "target": "bench",
                    },
                },
                {
                    "entity_id": "LINA",
                    "posture": "standing",
                    "evidence": "Лина stands in front of Hero.",
                    "placement": {
                        "relation": "in_front_of",
                        "target_kind": "character",
                        "target": "hero",
                    },
                },
            ]
        }
    )


def test_supported_changes_preserve_mechanics_and_survive_silent_turn():
    session = state()
    before = deepcopy(session.entity_states)
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    assert session.entity_states["LINA"] == before["LINA"]
    facts = project(session, CAST)
    assert facts["hero"]["posture"] == "sitting"
    assert facts["LINA"]["placement"]["target"] == "hero"
    session.entity_states[KEY] = reconcile(
        session, CAST, "They exchange a greeting.", SceneExtraction()
    )
    assert project(session, CAST) == facts
    assert (
        session.entity_states[KEY]["actors"]["hero"]["posture"]["evidence"]
        == "Hero sits on the bench."
    )
    assert "COAT" not in str(facts)


@pytest.mark.parametrize(
    "change",
    [
        {"entity_id": "ABSENT", "posture": "sitting", "evidence": "Hero sits on the bench."},
        {"entity_id": "hero", "posture": "sitting", "evidence": "A fabricated sentence."},
        {
            "entity_id": "hero",
            "evidence": "Hero sits on the bench.",
            "placement": {"relation": "on", "target_kind": "scene_object", "target": "throne"},
        },
        {
            "entity_id": "hero",
            "evidence": "Hero sits on the bench.",
            "placement": {"relation": "beside", "target_kind": "character", "target": "ABSENT"},
        },
    ],
)
def test_invalid_evidence_or_target_marks_staging_unconfirmed(change):
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, SceneExtraction(changes=[change]))
    assert session.entity_states[KEY]["status"] == "unconfirmed"
    assert project(session, CAST) == {}


def test_posture_change_does_not_keep_old_support_and_unknown_clears():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    text = "Hero stands up."
    result = SceneExtraction(
        changes=[{"entity_id": "hero", "posture": "standing", "evidence": text}]
    )
    session.entity_states[KEY] = reconcile(session, CAST, text, result)
    assert project(session, CAST)["hero"] == {"posture": "standing"}
    clear = SceneExtraction(changes=[{"entity_id": "hero", "clear": True, "evidence": text}])
    session.entity_states[KEY] = reconcile(session, CAST, text, clear)
    assert project(session, CAST)["hero"] == {}


def test_scene_movement_absence_and_toggle_invalidate_staging():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    assert "placement" not in project(session, CAST[1:])["LINA"]
    moved = [{**CAST[0], "position": "door"}, CAST[1]]
    assert "hero" not in project(session, moved)
    assert "placement" not in project(session, moved)["LINA"]
    session.current_scene_id = "OTHER"
    assert project(session, CAST) == {}
    session.current_scene_id = "START"
    write_settings(session, VnSettings(scene_staging=False))
    assert KEY not in session.entity_states
    write_settings(session, VnSettings(scene_staging=True))
    assert project(session, CAST) == {}


def test_narrator_projection_is_compact_and_snapshot_omits_provenance():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    npc = SimpleNamespace(
        id="LINA",
        name="Лина",
        entity_type="NPC",
        current_scene_id="START",
        is_hidden=False,
        spatial_position="garden",
    )
    block = narration_block(session, [npc], SimpleNamespace(id="hero", name="Hero"))
    assert "without listing or repeating" in block
    assert "sitting" in block and "in_front_of" in block
    assert "evidence" not in block and "source_hash" not in block and "COAT" not in block
    facts = _visible_facts(
        {
            "characters": [
                {
                    "id": "hero",
                    "posture": "sitting",
                    "placement": {
                        "relation": "on",
                        "target_kind": "scene_object",
                        "target": "bench",
                        "secret": "hidden",
                    },
                }
            ],
            "staging_status": "ready",
        }
    )
    assert facts["characters"][0]["posture"] == "sitting"
    assert "hidden" not in str(facts)


class StagingRoles(TurnRoles):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        from backend.engine.narrated_items.schema import SharedItemExtraction

        if schema is not SharedItemExtraction:
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        if self.fail:
            raise TimeoutError("Unavailable extractor")
        payload = json.loads(args[1])
        assert payload["completed_narration"] == TEXT
        staging = SceneExtraction(
            changes=[
                {
                    "entity_id": "LINA",
                    "posture": "standing",
                    "evidence": "Лина stands in front of Hero.",
                }
            ]
        )
        return SharedItemExtraction(staging=staging)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_real_turn_saves_narration_and_message_time_pose(monkeypatch, fail):
    import tests.test_vn_turn_integration as turns
    from backend.core.reliability_metrics import snapshot as metrics_snapshot

    before_metrics = metrics_snapshot()["staging"].get("reconciliations", 0)
    roles = StagingRoles(fail)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("backend.engine.scene_staging.runtime.GameMasterLLM", roles)
    monkeypatch.setattr(turns, "NARRATION", TEXT)
    async with TestSessionLocal() as db:
        user, _, session, _ = await seed_vn(db)
        write_settings(session, VnSettings(scene_staging=True))
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Hello")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert any(chunk.startswith("event: final") for chunk in chunks)
        assert roles.calls[-1][0] == "SharedItemExtraction"
        assert not any(call[0] == "SceneExtraction" for call in roles.calls)
        await db.refresh(session)
        message = await db.scalar(select(ChatMessage).where(ChatMessage.content == TEXT))
        snapshot = session.entity_states[REGISTRY_KEY]["snapshots"][message.id]
        facts = snapshot["visible_facts"]
        assert facts["staging_status"] == ("unconfirmed" if fail else "ready")
        npc = next(p for p in facts["characters"] if p["id"] == "LINA")
        assert npc.get("posture") == (None if fail else "standing")
        assert "HIDDEN_RING" not in str(facts)
        first_snapshot = deepcopy(snapshot)
        following = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in following.process_turn("Continue the conversation")]
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        next_prompt = str(roles.prompts[-1])
        assert ("ESTABLISHED SCENE STAGING" in next_prompt) is (not fail)
        await db.refresh(session)
        assert session.entity_states[REGISTRY_KEY]["snapshots"][message.id] == first_snapshot
    assert metrics_snapshot()["staging"].get("reconciliations", 0) - before_metrics == (
        0 if fail else 2
    )


def test_moving_target_invalidates_old_relative_position_but_repetition_does_not():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    same = SceneExtraction(
        changes=[{"entity_id": "hero", "posture": "sitting", "evidence": "Hero sits on the bench."}]
    )
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, same)
    assert project(session, CAST)["hero"]["placement"]["target"] == "bench"
    assert project(session, CAST)["LINA"]["placement"]["target"] == "hero"
    text = "Hero walks away."
    changed = SceneExtraction(changes=[{"entity_id": "hero", "clear": True, "evidence": text}])
    session.entity_states[KEY] = reconcile(session, CAST, text, changed)
    assert "placement" not in project(session, CAST)["LINA"]


@pytest.mark.asyncio
async def test_incomplete_narration_does_not_call_model_and_invalidates_old_staging(monkeypatch):
    from unittest.mock import Mock

    from backend.engine.scene_staging.runtime import reconcile_narration

    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    model = Mock(side_effect=AssertionError("No model call for incomplete narration"))
    monkeypatch.setattr("backend.engine.scene_staging.runtime.GameMasterLLM.for_role", model)
    await reconcile_narration(SimpleNamespace(state=session), "Hero starts to", completed=False)
    assert session.entity_states[KEY]["status"] == "unconfirmed"
    assert project(session, CAST) == {}
    model.assert_not_called()
