"""A partial garment is still worn and does not expose a whole body region."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.clothing.planning import validate_plan
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.clothing.visuals import character_visuals
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.narrated_items.wear import placement, unchanged_observation
from backend.engine.npc_actions.contracts import Adjust
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VNProgressionIntent
from tests.test_clothing_runtime import ACTION, action, profile, world


@pytest.mark.parametrize("previous_regions", [[], ["arms"]])
async def test_coarse_adjustment_preserves_known_coverage_through_restore_and_remove(
    previous_regions,
):
    manager, npc, scenes = world()
    before = deepcopy(manager.avatar.inventory)
    manager.avatar.visual_profile = profile("coat")
    manager.avatar.visual_profile["worn"][0]["uncovered_regions"] = previous_regions
    for turn, operation, partial in [
        (1, "adjust", True),
        (2, "adjust", False),
        (3, "remove", False),
    ]:
        manager._vn_player_message_id = f"turn-{turn}"
        event = GameEvent()
        request = action(
            operation=operation,
            partially_removed=partial,
            uncovered_regions=["torso", "arms"] if partial else [],
        )
        event._vn_clothing_plan = validate_plan(
            manager, VNProgressionIntent(wardrobe_actions=[request]), ACTION, "", [npc], scenes
        )
        await apply_wardrobe(manager, event, manager.state.entity_states)
        assert not event._vn_clothing_plan.errors
        current = load_profile(manager.avatar.visual_profile)
        assert current is not None
        assert manager.avatar.inventory == before
        if operation == "remove":
            assert not current.worn
            continue
        (entry,) = current.worn
        assert entry.partially_removed is partial
        assert entry.uncovered_regions == (previous_regions if partial else [])
        appearance = visible_character(current.model_dump(), before)
        assert bool(appearance["clothing"][0].get("partially_removed")) is partial
        visual = character_visuals(manager.avatar, before)
        assert ("partially removed" in visual["clothing"]) is partial


def test_confirmation_and_restoration_do_not_confuse_unknown_with_normal_coverage():
    snapshot = profile("coat")
    snapshot["worn"][0]["partially_removed"] = True
    actor = {"id": "actor", "visual_profile": snapshot}
    props = dict(
        item_id="coat",
        source_owner="actor",
        destination_owner="actor",
        disposition="worn",
        basis="observed_wear",
        evidence="The same coat is still on.",
    )
    for fields, partial, unchanged in [
        ({}, True, True),
        ({"uncovered_regions": []}, False, False),
        ({"partially_removed": False}, False, False),
        ({"partially_removed": True, "uncovered_regions": ["torso", "arms"]}, True, False),
    ]:
        proposal = ItemAction.model_validate({**props, **fields})
        assert unchanged_observation(proposal, actor, "coat") is unchanged
        result = placement(
            proposal, actor, "coat", same_owner=True, narration=proposal.evidence, request_id="turn"
        )
        assert result is not None and result.partially_removed is partial
        assert result.uncovered_regions == []
    with pytest.raises(ValidationError):
        ItemAction.model_validate({**props, "disposition": "carried", "partially_removed": True})


def test_old_adjust_requests_keep_their_serialized_shape():
    normal = {"tool": "adjust_clothing", "item_id": "coat", "uncovered_regions": []}
    assert Adjust.model_validate(normal).model_dump() == normal
    with pytest.raises(ValidationError):
        Adjust.model_validate({**normal, "partially_removed": True, "uncovered_regions": ["torso"]})
