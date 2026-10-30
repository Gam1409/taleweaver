"""Frozen visual context has a single owner and an explicit state contract."""

from copy import deepcopy

from backend.engine.clothing.frames import Figure, VisibleFrame
from backend.engine.scene_illustrations.visual_context import STATE_AUTHORITY, VisualContext


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


def test_context_and_pending_request_do_not_alias_saved_snapshot():
    saved = snapshot()
    before = deepcopy(saved)
    context = VisualContext.from_snapshot(saved)
    pending = context.pending()
    pending["visible_facts"]["characters"][0]["clothing"] = "later blue coat"
    initial = context.initial_data()
    initial["visible_facts"]["setting"] = "different room"
    assert saved == before
    assert context.facts["characters"][0]["clothing"] == "gray coat"
    assert context.facts["setting"] == "Hospital room"


def test_frame_cannot_overwrite_frozen_clothing_or_drop_uncertainty():
    context = VisualContext.from_snapshot(snapshot())
    frame = VisibleFrame(figures=[Figure(character_id="VISITOR", action="withdrawing")])
    data = context.composed_data(frame)
    figure = data["characters"][0]
    assert figure["clothing"] == "gray coat"
    assert figure["clothing_detail_limited"] is True
    assert figure["action"] == "withdrawing"
    assert figure["posture"] == "unspecified"
    assert data["lighting"] == "morning light"
    prompt = context.prompt("Final visible moment.", data)
    assert STATE_AUTHORITY in prompt
    assert "later blue coat" not in prompt


def test_context_preserves_existing_managed_boundary_and_emotions():
    context = VisualContext.from_snapshot(snapshot())
    assert "[surprised]" in context.passage
    assert "<breath>" not in context.passage
    assert "passage" not in context.initial_data()
    restored = VisualContext.from_pending(context.pending())
    assert restored == context
    unmanaged = VisualContext.from_snapshot(snapshot(False))
    assert unmanaged.initial_data()["passage"] == context.passage


def test_missing_clothing_is_not_created_by_context():
    saved = snapshot()
    del saved["visible_facts"]["characters"][0]["clothing"]
    context = VisualContext.from_snapshot(saved)
    data = context.composed_data(VisibleFrame(figures=[Figure(character_id="VISITOR")]))
    assert "clothing" not in data["characters"][0]
    assert data["characters"][0]["clothing_detail_limited"] is True
