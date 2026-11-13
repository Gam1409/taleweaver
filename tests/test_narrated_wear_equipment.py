"""Narrated wear keeps one mechanical placement and canonical layered ownership."""

from copy import deepcopy

import pytest

from backend.engine.clothing.profiles import owned_items, validate_profile
from backend.engine.command_parser import CommandParser
from backend.engine.stat_aggregator import calculate_total_stats
from backend.engine.visual_novel.continuity import PLAYER, Possessions
from backend.models.avatar import Avatar
from tests.test_narrated_items import action, fixtures, run


def ring(identifier="RING", *, slots=None, bonus=3):
    return {
        "id": identifier,
        "name": "Plain ring" if identifier == "RING" else identifier,
        "description": "A plain metal ring.",
        "item_type": "WEARABLE",
        "slot": "Ring_1",
        "wearable_slots": slots or ["Ring_1", "Ring_2"],
        "clothing": {"layer": 2, "coverage": ["hands"], "category": "accessory"},
        "stat_modifier_dexterity": bonus,
    }


def setup_ring(*, slots=None, player_owned=False):
    actors, _ = fixtures()
    item = ring(slots=slots)
    source = PLAYER if player_owned else "NPC"
    for actor in actors.values():
        actor["inventory"] = []
        actor["resolved_inventory"] = []
        actor["equipment"] = {}
        actor["visual_profile"]["worn"] = []
    actors[source]["inventory"] = [deepcopy(item)]
    actors[source]["resolved_inventory"] = [deepcopy(item)]
    snapshot = Possessions(items={"RING": deepcopy(item)}, owners={"RING": source})
    return actors, snapshot


def wear(**overrides):
    return action(
        item_id="RING",
        disposition="worn",
        evidence="Anna gives the hero the plain ring, which the hero puts on.",
        **overrides,
    )


def avatar_from(actor):
    return Avatar(
        id="fixture-avatar",
        user_id="fixture-owner",
        name="Neutral hero",
        strength=10,
        dexterity=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
        armor_class=10,
        stats={},
        status_effects=[],
        inventory=deepcopy(actor["inventory"]),
        equipment=deepcopy(actor["equipment"]),
        visual_profile=deepcopy(actor["visual_profile"]),
    )


@pytest.mark.parametrize("slots", ["Ring_1", ["Ring_1"], ["Ring_1", "Ring_2"]])
def test_narrated_wear_equips_once_and_slash_unequip_leaves_one_item(slots):
    actors, snapshot = setup_ring(slots=slots)
    before = deepcopy(actors)
    changed, accepted, errors = run([wear()], actors, snapshot)
    assert not errors and len(accepted) == 1
    actor = changed[PLAYER]
    assert [
        slot for slot, value in actor["equipment"].items() if value and value["id"] == "RING"
    ] == ["Ring_1"]
    assert actor["inventory"] == []
    assert actor["resolved_inventory"] == [snapshot.items["RING"]]
    assert set(owned_items(actor["inventory"], equipment=actor["equipment"])) == {"RING"}
    validate_profile(actor["visual_profile"], actor["inventory"], equipment=actor["equipment"])
    avatar = avatar_from(actor)
    assert calculate_total_stats(avatar)["dexterity"] == 13
    response = CommandParser.parse_command(avatar, "/unequip Ring_1")
    assert response.startswith("[TRIGGER_UNEQUIP] RING")
    assert avatar.inventory == [snapshot.items["RING"]]
    assert calculate_total_stats(avatar)["dexterity"] == 10
    assert "Nothing is equipped" in CommandParser.parse_command(avatar, "/unequip Ring_1")
    assert CommandParser.parse_command(avatar, "/equip Plain ring").startswith(
        "[TRIGGER_EQUIP] RING"
    )
    assert avatar.inventory == []
    assert calculate_total_stats(avatar)["dexterity"] == 13
    assert actors == before


@pytest.mark.parametrize("occupied", [[], ["Ring_1"], ["Ring_1", "Ring_2"]])
def test_alternatives_preserve_occupied_slots_and_choose_only_one_free_slot(occupied):
    actors, snapshot = setup_ring()
    existing = {slot: ring(f"OTHER_{slot}", slots=[slot], bonus=1) for slot in occupied}
    actors[PLAYER]["equipment"] = deepcopy(existing)
    actors[PLAYER]["visual_profile"]["worn"] = [
        {"item_id": item["id"]} for item in existing.values()
    ]
    changed, accepted, errors = run([wear()], actors, snapshot)
    assert accepted and not errors
    actor = changed[PLAYER]
    assert all(actor["equipment"][slot] == item for slot, item in existing.items())
    placements = [
        slot for slot, item in actor["equipment"].items() if item and item["id"] == "RING"
    ]
    expected = next((slot for slot in ("Ring_1", "Ring_2") if slot not in occupied), None)
    assert placements == ([expected] if expected else [])
    assert actor["inventory"] == ([] if expected else [snapshot.items["RING"]])
    assert {row["item_id"] for row in actor["visual_profile"]["worn"]} == {
        "RING",
        *(item["id"] for item in existing.values()),
    }


@pytest.mark.parametrize("prior_slot", [None, "Ring_2"])
def test_existing_player_item_wear_preserves_its_selected_equipment_slot(prior_slot):
    actors, snapshot = setup_ring(player_owned=True)
    if prior_slot:
        actors[PLAYER]["inventory"] = []
        actors[PLAYER]["equipment"] = {prior_slot: deepcopy(snapshot.items["RING"])}
        actors[PLAYER]["visual_profile"]["worn"] = [{"item_id": "RING"}]
    changed, accepted, errors = run([wear(source_owner=PLAYER)], actors, snapshot)
    assert accepted and not errors
    actor = changed[PLAYER]
    assert actor["inventory"] == []
    assert [slot for slot, item in actor["equipment"].items() if item and item["id"] == "RING"] == [
        prior_slot or "Ring_1"
    ]
    assert calculate_total_stats(avatar_from(actor))["dexterity"] == 13


def test_npc_wear_keeps_one_canonical_inventory_item_without_player_equipment():
    actors, snapshot = setup_ring()
    changed, accepted, errors = run([wear(destination_owner="NPC")], actors, snapshot)
    assert accepted and not errors
    assert changed["NPC"]["inventory"] == [snapshot.items["RING"]]
    assert changed["NPC"]["equipment"] == {}
    assert changed["NPC"]["visual_profile"]["worn"] == [
        {"item_id": "RING", "uncovered_regions": []}
    ]


def test_layered_worn_garment_keeps_occupied_equipment_and_both_canonical_items():
    actors, snapshot = fixtures()
    inner = {**deepcopy(snapshot.items["SHIRT"]), "id": "INNER", "name": "Inner shirt"}
    actors[PLAYER]["equipment"] = {"Chest": inner}
    actors[PLAYER]["visual_profile"]["worn"] = [{"item_id": "INNER"}]
    changed, accepted, errors = run([action(disposition="worn")], actors, snapshot)
    assert accepted and not errors
    actor = changed[PLAYER]
    assert actor["equipment"] == {"Chest": inner}
    assert actor["inventory"] == [snapshot.items["SHIRT"]]
    assert {row["item_id"] for row in actor["visual_profile"]["worn"]} == {"INNER", "SHIRT"}
    validate_profile(actor["visual_profile"], actor["inventory"], equipment=actor["equipment"])


def test_legacy_slot_aliases_do_not_hide_an_occupied_canonical_slot():
    actors, snapshot = setup_ring(slots=["ring_1", "Ring_2"])
    other = ring("OTHER", bonus=1)
    actors[PLAYER]["equipment"] = {"ring_1": other}
    changed, accepted, errors = run([wear()], actors, snapshot)
    assert accepted and not errors
    assert changed[PLAYER]["equipment"]["ring_1"] == other
    assert changed[PLAYER]["equipment"]["Ring_2"]["id"] == "RING"
    assert changed[PLAYER]["inventory"] == []


def test_invalid_legacy_wearable_slot_is_not_created_as_mechanical_equipment():
    actors, snapshot = setup_ring(slots=["UnknownSlot", "Ring_2"])
    changed, accepted, errors = run([wear()], actors, snapshot)
    assert accepted and not errors
    assert changed[PLAYER]["equipment"] == {"Ring_2": snapshot.items["RING"]}
    assert changed[PLAYER]["inventory"] == []


@pytest.mark.parametrize("disposition", ["carried", "held"])
def test_ordinary_acquisition_stays_carried_and_never_equips(disposition):
    actors, snapshot = setup_ring()
    ordinary = {
        "id": "BOOK",
        "name": "Plain notebook",
        "description": "A small notebook.",
        "item_type": "DEFAULT",
    }
    actors["NPC"]["inventory"] = [ordinary]
    actors["NPC"]["resolved_inventory"] = [ordinary]
    snapshot = Possessions(items={"BOOK": ordinary}, owners={"BOOK": "NPC"})
    proposal = action(
        item_id="BOOK", disposition=disposition, evidence="Anna hands the hero the plain notebook."
    )
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert accepted and not errors
    assert changed[PLAYER]["inventory"] == [ordinary]
    assert changed[PLAYER]["equipment"] == {}
