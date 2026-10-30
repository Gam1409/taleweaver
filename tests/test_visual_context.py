"""Frozen visual context has a single owner and an explicit state contract."""

from copy import deepcopy

from backend.engine.scene_illustrations.source_quality import build_prompt
from backend.engine.scene_illustrations.visual_context import VisualContext


def snapshot(managed=True):
    return {
        "narration": "[surprised] <breath> The visitor steps back from the window.",
        "visible_facts": {
            "setting": "Hospital room",
            "lighting": "morning light",
            "characters": [
                {
                    "id": "VISITOR",
                    "name": "Visitor",
                    "appearance": "short brown hair",
                    "clothing": "gray coat",
                    "managed_clothing": managed,
                    "clothing_detail_limited": True,
                }
            ],
        },
    }


def test_context_does_not_alias_saved_snapshot():
    saved = snapshot()
    before = deepcopy(saved)
    context = VisualContext.from_snapshot(saved)
    context.facts["characters"][0]["clothing"] = "later blue coat"
    context.facts["setting"] = "different room"
    assert saved == before


def test_prompt_keeps_frozen_clothing_and_uncertainty_alongside_action():
    saved = snapshot()
    context = VisualContext.from_snapshot(saved)
    saved["visible_facts"]["characters"][0]["clothing"] = "later blue coat"
    prompt = build_prompt(context)
    assert "gray coat" in prompt
    assert "clothing_detail_limited" in prompt
    assert "steps back" in prompt
    assert "morning light" in prompt
    assert "later blue coat" not in prompt


def test_context_keeps_source_and_emotions_for_managed_and_unmanaged_cast():
    for managed in (True, False):
        context = VisualContext.from_snapshot(snapshot(managed))
        prompt = build_prompt(context)
        assert "[surprised]" in prompt
        assert "<breath>" not in prompt
        assert "steps back from the window" in prompt


def test_missing_clothing_is_not_created_by_context():
    saved = snapshot()
    del saved["visible_facts"]["characters"][0]["clothing"]
    context = VisualContext.from_snapshot(saved)
    assert "clothing" not in context.facts["characters"][0]
    assert context.facts["characters"][0]["clothing_detail_limited"] is True
