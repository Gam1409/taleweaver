"""Completed item actions preserve ownership, evidence, clothing and replay safety."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.runtime import KEY, reconcile_items
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER, Possessions


def fixtures():
    shirt = {
        "id": "SHIRT",
        "name": "Shirt",
        "description": "A blue shirt.",
        "clothing": {"layer": 1, "coverage": ["torso"], "opaque": True},
        "wearable_slots": ["Chest"],
    }
    actors = {
        PLAYER: {
            "id": PLAYER,
            "name": "Hero",
            "age_years": 30,
            "inventory": [],
            "resolved_inventory": [],
            "equipment": {},
            "visual_profile": {"appearance": {"age_years": 30, "features": "Traveler"}, "worn": []},
        },
        "NPC": {
            "id": "NPC",
            "name": "Anna",
            "age_years": 30,
            "inventory": [shirt],
            "resolved_inventory": [shirt],
            "equipment": {},
            "visual_profile": {"appearance": {"age_years": 30}, "worn": [{"item_id": "SHIRT"}]},
        },
    }
    return actors, Possessions(items={"SHIRT": shirt}, owners={"SHIRT": "NPC"})


def action(**overrides):
    return ItemAction.model_validate(
        {
            "item_id": "SHIRT",
            "source_owner": "NPC",
            "destination_owner": PLAYER,
            "disposition": "carried",
            "evidence": "Anna handed the shirt to the hero.",
            "basis": "completed",
            **overrides,
        }
    )


def run(actions, actors=None, snapshot=None, narration=None, detailed=True):
    defaults = fixtures()
    return apply_actions(
        ItemExtraction(actions=actions),
        actors or defaults[0],
        snapshot or defaults[1],
        narration or " ".join(a.evidence for a in actions),
        detailed=detailed,
        session_id="SESSION",
        message_id="TURN",
    )


def test_transfer_removes_worn_source_preserves_identity_and_does_not_equip_recipient():
    actors, snapshot = fixtures()
    before = deepcopy(actors)
    changed, accepted, errors = run([action()], actors, snapshot)
    assert not errors and len(accepted) == 1
    assert changed["NPC"]["inventory"] == []
    assert changed["NPC"]["visual_profile"]["worn"] == []
    assert changed[PLAYER]["inventory"][0] == snapshot.items["SHIRT"]
    assert changed[PLAYER]["equipment"] == {}
    assert changed[PLAYER]["visual_profile"]["worn"] == []
    assert actors == before


@pytest.mark.parametrize("basis", ["attempt", "claim", "hypothetical", "uncertain"])
def test_incomplete_actions_never_transfer(basis):
    actors, _ = fixtures()
    changed, accepted, errors = run([action(basis=basis)])
    assert errors and not accepted and changed == actors


def test_bad_quote_or_absent_owner_preserves_both_inventories():
    actors, _ = fixtures()
    for proposal in (action(evidence="Unsaid action."), action(source_owner="ABSENT")):
        changed, accepted, errors = run([proposal], narration="Anna handed the shirt to the hero.")
        assert errors and not accepted and changed == actors


def test_new_clothing_gets_stable_id_description_and_provenance():
    proposal = action(
        item_id=None,
        new_item={
            "name": "Scarf",
            "description": "A plain green scarf.",
            "kind": "clothing",
            "clothing": {"layer": 2, "coverage": ["torso"]},
            "wearable_slots": ["Neck"],
        },
        evidence="Anna handed the green scarf to the hero.",
    )
    first, accepted, errors = run([proposal])
    second, _, _ = run([proposal])
    assert not errors
    item = first[PLAYER]["inventory"][0]
    assert item["id"] == second[PLAYER]["inventory"][0]["id"]
    assert item["description"] == "A plain green scarf."
    assert item["clothing_origin"]["source_message_id"] == "TURN"
    assert item["id"] == accepted[0]["item"]["id"]


@pytest.mark.parametrize("age,detailed", [(None, True), (17, True), (30, False)])
def test_new_inner_clothing_requires_existing_adult_source_and_detail(age, detailed):
    actors, snapshot = fixtures()
    actors["NPC"]["age_years"] = age
    proposal = action(
        item_id=None,
        new_item={
            "name": "Undershirt",
            "description": "An ordinary cotton undershirt.",
            "kind": "clothing",
            "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
            "wearable_slots": ["Chest"],
        },
    )
    changed, accepted, errors = run([proposal], actors, snapshot, detailed=detailed)
    assert errors and not accepted and changed == actors


def test_failed_wear_does_not_remove_item_from_source():
    actors, snapshot = fixtures()
    actors[PLAYER]["visual_profile"] = None
    changed, accepted, errors = run([action(disposition="worn")], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_already_transferred_item_is_not_duplicated_or_unequipped():
    actors, snapshot = fixtures()
    actors[PLAYER]["inventory"] = actors["NPC"]["inventory"]
    actors[PLAYER]["equipment"] = {"Chest": snapshot.items["SHIRT"]}
    actors["NPC"]["inventory"] = []
    snapshot.owners["SHIRT"] = PLAYER
    changed, accepted, errors = run([action()], actors, snapshot)
    assert not errors and not accepted and changed == actors


@pytest.mark.asyncio
async def test_runtime_persists_change_and_deduplicates_retries():
    actors, snapshot = fixtures()
    avatar = SimpleNamespace(**actors[PLAYER])
    npc = SimpleNamespace(id="NPC", entity_type="NPC", age_years=30)
    manager = SimpleNamespace(
        avatar=avatar,
        state=SimpleNamespace(entity_states={}, session_id="SESSION", current_scene_id="ROOM"),
        game_id="SESSION",
        user=SimpleNamespace(),
        db=SimpleNamespace(),
        _vn_player_message_id="TURN",
    )
    llm = SimpleNamespace(
        model="test",
        aexecute_complex_task=AsyncMock(return_value=ItemExtraction(actions=[action()])),
    )
    with (
        patch(
            "backend.engine.narrated_items.runtime.session_objects", AsyncMock(return_value=[npc])
        ),
        patch("backend.engine.narrated_items.runtime.actor_records", return_value=actors),
        patch("backend.engine.narrated_items.runtime.possession_snapshot", return_value=snapshot),
        patch(
            "backend.engine.narrated_items.runtime.detail_settings", return_value={"detailed": True}
        ),
        patch("backend.engine.narrated_items.runtime.release_for_model", AsyncMock()),
        patch("backend.engine.narrated_items.runtime.role_timeout", return_value=10),
        patch("backend.engine.narrated_items.runtime.GameMasterLLM.for_role", return_value=llm),
    ):
        messages = await reconcile_items(manager, action().evidence, completed=True, resolution="")
        assert messages and "Shirt" in messages[0]
        assert (
            await reconcile_items(manager, action().evidence, completed=True, resolution="") == []
        )
    assert llm.aexecute_complex_task.await_count == 1
    assert avatar.inventory[0]["id"] == "SHIRT"
    assert manager.state.entity_states["NPC"]["inventory"] == []
    assert manager.state.entity_states["NPC"]["visual_profile"]["worn"] == []
    assert manager.state.entity_states[KEY]["accepted"][0]["evidence"] == action().evidence


@pytest.mark.asyncio
async def test_incomplete_or_guardrail_rejected_narration_never_calls_model():
    manager = SimpleNamespace(state=SimpleNamespace(entity_states={}), _vn_player_message_id="TURN")
    assert (
        await reconcile_items(manager, "An unfinished transfer", completed=False, resolution="")
        == []
    )
    messages = await reconcile_items(
        manager, "An invalid transfer", completed=True, resolution="", blocked=True
    )
    assert messages and manager.state.entity_states[KEY]["status"] == "needs_review"


def test_gift_can_use_previous_narration_but_not_only_current_player_claim():
    from backend.engine.clothing.planning import validate_plan
    from backend.engine.visual_novel.intent import VNProgressionIntent
    from tests.test_clothing_runtime import creation, world

    manager, npc, scenes = world()
    previous = "Anna folded her red scarf and offered it to the traveler."
    player = "I accept the offered red scarf."
    proposal = VNProgressionIntent(
        garment_creations=[
            creation(
                acquisition="gift",
                source_id="ANNA",
                source_evidence=previous,
                evidence=player,
                name="Red scarf",
                wear=False,
            )
        ]
    )
    assert len(validate_plan(manager, proposal, player, previous, [npc], scenes).creations) == 1
    assert not validate_plan(manager, proposal, player + previous, "", [npc], scenes).creations
