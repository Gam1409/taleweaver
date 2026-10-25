"""Runtime clothing details require frozen opt-in and an explicitly adult actor."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.clothing.actions import GarmentCreation, WardrobeAction
from backend.engine.clothing.planning import WardrobePlan, validate_plan
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.clothing.schema import VisualProfile
from backend.engine.command_parser import CommandParser
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot


class EmptyDatabase:
    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: [])


def manager_for(*, age=None, detailed=False, underwear=True, worn=False):
    item = {
        "id": "GARMENT",
        "name": "Plain garment",
        "clothing": {
            "layer": 0,
            "coverage": ["torso"],
            "underwear": underwear,
            "description": "Neutral fabric",
        },
    }
    avatar = SimpleNamespace(
        name="Player",
        description="An adult traveler.",
        inventory=[item],
        equipment={},
        visual_profile={
            "version": 1,
            "appearance": {"age_years": age},
            "worn": [{"item_id": item["id"]}] if worn else [],
        },
    )
    state = SimpleNamespace(
        session_id="clothing-gate",
        current_scene_id="ROOM",
        entity_states={
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": detailed}}
            }
        },
    )
    avatar.visual_profile = VisualProfile.model_validate(avatar.visual_profile).model_dump()
    return SimpleNamespace(
        avatar=avatar, state=state, db=EmptyDatabase(), _vn_player_message_id="request-1"
    )


def evidence():
    return {
        "actor_id": PLAYER,
        "source": "player_action",
        "evidence": "I put on the garment.",
        "basis": "performed",
        "agency": "self_action",
        "reason": "The player performs the clothing change.",
    }


async def run_plan(manager, *, actions=None, creations=None):
    event = GameEvent()
    event._vn_clothing_plan = WardrobePlan(
        "request-1", "ROOM", actions=actions or [], creations=creations or []
    )
    states = deepcopy(manager.state.entity_states)
    await apply_wardrobe(manager, event, states)
    return event


@pytest.mark.parametrize(
    "age,detailed,allowed",
    [(None, True, False), (17, True, False), (18, False, False), (18, True, True)],
)
@pytest.mark.parametrize("operation", ["wear", "adjust"])
async def test_underlayer_wear_and_adjust_require_known_adult_and_opt_in(
    age, detailed, allowed, operation
):
    manager = manager_for(age=age, detailed=detailed, worn=operation == "adjust")
    before = deepcopy(manager.avatar.visual_profile)
    action = WardrobeAction(
        **evidence(), item_id="GARMENT", operation=operation, uncovered_regions=["torso"]
    )
    event = await run_plan(manager, actions=[action])
    if allowed:
        assert manager.avatar.visual_profile["worn"][0]["uncovered_regions"] == ["torso"]
    else:
        assert manager.avatar.visual_profile == before
        assert "Detailed garment tracking is unavailable" in event.narrative_description


@pytest.mark.parametrize("age,detailed", [(None, True), (17, True), (18, False), (18, True)])
async def test_removal_preserves_owned_underlayer_even_when_details_disabled(age, detailed):
    manager = manager_for(age=age, detailed=detailed, worn=True)
    before = deepcopy(manager.avatar.inventory)
    await run_plan(
        manager, actions=[WardrobeAction(**evidence(), item_id="GARMENT", operation="remove")]
    )
    assert manager.avatar.visual_profile["worn"] == []
    assert manager.avatar.inventory == before


@pytest.mark.parametrize(
    "age,detailed,allowed",
    [(None, True, False), (17, True, False), (18, False, False), (18, True, True)],
)
async def test_underlayer_creation_requires_known_adult_and_opt_in(age, detailed, allowed):
    manager = manager_for(age=age, detailed=detailed)
    creation = GarmentCreation(
        **evidence(),
        acquisition="wardrobe",
        source_id="ROOM",
        source_evidence="A wardrobe holds clothing.",
        name="New plain garment",
        clothing=manager.avatar.inventory[0]["clothing"],
        wear=True,
    )
    event = await run_plan(manager, creations=[creation])
    assert len(manager.avatar.inventory) == (2 if allowed else 1)
    assert bool(manager.avatar.visual_profile["worn"]) is allowed
    if not allowed:
        assert "Detailed garment tracking is unavailable" in event.narrative_description


async def test_ordinary_clothing_does_not_require_age_or_detail_opt_in():
    manager = manager_for(underwear=False)
    await run_plan(
        manager, actions=[WardrobeAction(**evidence(), item_id="GARMENT", operation="wear")]
    )
    assert manager.avatar.visual_profile["worn"][0]["item_id"] == "GARMENT"


@pytest.mark.parametrize(
    "basis", ["future", "past", "negated", "hypothetical", "claim", "uncertain"]
)
def test_noncurrent_or_unperformed_clothing_requests_do_not_become_actions(basis):
    manager = manager_for(age=30, detailed=True)
    data = {**evidence(), "basis": basis}
    action = WardrobeAction(**data, item_id="GARMENT", operation="wear")
    proposal = SimpleNamespace(wardrobe_actions=[action], garment_creations=[])
    plan = validate_plan(manager, proposal, data["evidence"], "", [], [])
    assert plan.actions == []
    assert plan.errors


def test_unavailable_source_cannot_create_clothing():
    manager = manager_for(age=30, detailed=True)
    creation = GarmentCreation(
        **evidence(),
        acquisition="wardrobe",
        source_id="OTHER_ROOM",
        source_evidence="A wardrobe holds clothing.",
        name="New plain garment",
        clothing=manager.avatar.inventory[0]["clothing"],
        wear=True,
    )
    proposal = SimpleNamespace(wardrobe_actions=[], garment_creations=[creation])
    plan = validate_plan(
        manager,
        proposal,
        creation.evidence,
        "",
        [],
        [{"id": "ROOM", "description": "An empty room."}],
    )
    assert plan.creations == []
    assert plan.errors


async def test_natural_removal_of_mechanically_equipped_garment_preserves_possession():
    manager = manager_for(underwear=False)
    item = manager.avatar.inventory[0]
    item.update(slot="Chest", item_type="WEARABLE", stat_modifier_armor_class=2)
    original = deepcopy(item)
    CommandParser._handle_equip(manager.avatar, item["name"])
    assert manager.avatar.inventory == []
    assert manager.avatar.equipment["Chest"] == original
    await run_plan(
        manager,
        actions=[WardrobeAction(**evidence(), item_id="GARMENT", operation="remove")],
    )
    assert manager.avatar.equipment["Chest"] is None
    assert manager.avatar.inventory == [original]
    assert manager.avatar.visual_profile["worn"] == []


def test_mechanically_equipped_garment_remains_player_owned_for_transfers():
    manager = manager_for(underwear=False)
    item = manager.avatar.inventory[0]
    item.update(slot="Chest", item_type="WEARABLE")
    CommandParser._handle_equip(manager.avatar, item["name"])
    snapshot = possession_snapshot(manager, [])
    assert snapshot.owners["GARMENT"] == PLAYER
    assert snapshot.items["GARMENT"]["clothing"] == item["clothing"]
