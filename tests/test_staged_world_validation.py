"""Staged responses must preserve canonical identity, topology and item ownership."""

from copy import deepcopy

import pytest

from backend.engine.staged_world.validation import (
    CATEGORIES,
    validate_batch,
    validate_manifest,
    validate_plan,
)


@pytest.fixture
def plan():
    def seed(identifier, name, scene="", owner=""):
        return {
            "id": identifier,
            "name": name,
            "summary": "A planned detail",
            "start_scene_id": scene,
            "owner_id": owner,
        }

    return {
        **dict.fromkeys(CATEGORIES, []),
        "foundation": {"language": "Russian", "plot": "A reunion", "rules": "No magic"},
        "protagonist": seed("PROTAGONIST", "Иван"),
        "scenes": [seed("CITY", "Город"), seed("TAVERN", "Таверна")],
        "npcs": [seed("LENA", "Лена", "TAVERN")],
        "objects": [
            seed("KEY", "Ключ", "CITY", "PROTAGONIST"),
            seed("LETTER", "Письмо", "TAVERN", "LENA"),
            seed("BOX", "Сундук", "TAVERN"),
            seed("GEM", "Камень", "TAVERN", "BOX"),
        ],
        "exits": [
            {"from_scene_id": "CITY", "to_scene_id": "TAVERN", "label": "Дверь", "is_locked": False}
        ],
    }


@pytest.fixture
def manifest(plan):
    return {
        **deepcopy(plan["foundation"]),
        **{kind: deepcopy(plan[kind]) for kind in CATEGORIES},
        "exits": deepcopy(plan["exits"]),
        "protagonist": {
            "name": "Иван",
            "starting_inventory": ["KEY"],
            "starting_equipment": {"MainHand": "KEY"},
        },
        "npcs": [
            {"id": "LENA", "name": "Лена", "start_scene_id": "TAVERN", "inventory": ["LETTER"]}
        ],
        "objects": [
            {
                "id": row["id"],
                "name": row["name"],
                "start_scene_id": row["start_scene_id"],
                "item_type": "CONTAINER" if row["id"] == "BOX" else "PICKABLE",
                "inventory": ["GEM"] if row["id"] == "BOX" else [],
            }
            for row in plan["objects"]
        ],
    }


def test_valid_russian_content_with_ascii_identifiers(plan, manifest):
    validate_plan(plan)
    validate_manifest(manifest, plan)


@pytest.mark.parametrize("identifier", ["ЛЕС", "CITY/1", "CITY-1", "", "A" * 65, "PROTAGONIST"])
def test_plan_rejects_noncanonical_or_reserved_identifiers(plan, identifier):
    plan["scenes"][0]["id"] = identifier
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_plan_rejects_duplicate_ids_across_categories(plan):
    plan["npcs"][0]["id"] = "KEY"
    with pytest.raises(ValueError, match="Duplicate"):
        validate_plan(plan)


def test_plan_requires_reachable_scene_graph(plan):
    plan["exits"] = []
    with pytest.raises(ValueError, match="unreachable.*TAVERN"):
        validate_plan(plan)


def test_locked_passage_is_still_topologically_reachable(plan):
    plan["exits"][0].update(is_locked=True, item_to_unlock="KEY")
    validate_plan(plan)


@pytest.mark.parametrize("owner", ["GHOST", "BOX", "GEM"])
def test_plan_rejects_missing_or_cyclic_ownership(plan, owner):
    plan["objects"][2]["owner_id"] = owner
    with pytest.raises(ValueError, match="unknown ID|Cyclic"):
        validate_plan(plan)


def test_batch_rejects_invented_identity(plan, manifest):
    row = manifest["npcs"][0]
    row["id"] = "SOMEONE_ELSE"
    with pytest.raises(ValueError, match="unplanned ID"):
        validate_batch("npcs", [row], plan)


@pytest.mark.parametrize(("field", "value"), [("name", "Helen"), ("start_scene_id", "CITY")])
def test_batch_cannot_change_frozen_identity_or_placement(plan, manifest, field, value):
    manifest["npcs"][0][field] = value
    with pytest.raises(ValueError, match="planned"):
        validate_batch("npcs", manifest["npcs"], plan)


@pytest.mark.parametrize("field", ["equipped_weapon_id", "equipped_armor_id"])
def test_batch_equipment_references_must_exist(plan, manifest, field):
    manifest["npcs"][0][field] = "GHOST"
    with pytest.raises(ValueError, match="unknown ID"):
        validate_batch("npcs", manifest["npcs"], plan)


def test_batch_nested_action_and_attack_trigger_references(plan, manifest):
    manifest["npcs"][0]["attack_trigger"] = {"required_defeated_npc_id": "GHOST"}
    with pytest.raises(ValueError, match="attack_trigger.*unknown ID"):
        validate_batch("npcs", manifest["npcs"], plan)


@pytest.mark.parametrize("field", ["combination_ingredients", "inventory"])
def test_batch_item_list_references_must_exist(plan, manifest, field):
    row = manifest["objects"][0]
    row[field] = ["GHOST"]
    with pytest.raises(ValueError, match="unknown ID"):
        validate_batch("objects", [row], plan)


def test_protagonist_equipment_references_must_exist(plan, manifest):
    manifest["protagonist"]["starting_equipment"]["Head"] = "GHOST"
    with pytest.raises(ValueError, match="starting_equipment.Head"):
        validate_batch("protagonist", manifest["protagonist"], plan)


def test_batch_duplicates_fail_before_checkpoint(plan, manifest):
    with pytest.raises(ValueError, match="duplicate IDs"):
        validate_batch("npcs", manifest["npcs"] * 2, plan)


def test_assembled_world_cannot_omit_a_planned_item(plan, manifest):
    manifest["objects"].pop()
    with pytest.raises(ValueError):
        validate_manifest(manifest, plan)


def test_item_cannot_belong_to_two_characters(plan, manifest):
    manifest["npcs"][0]["inventory"].append("KEY")
    with pytest.raises(ValueError, match="planned owner"):
        validate_manifest(manifest, plan)


def test_loose_object_cannot_silently_become_npc_inventory(plan, manifest):
    manifest["npcs"][0]["inventory"].append("BOX")
    with pytest.raises(ValueError, match="planned owner"):
        validate_manifest(manifest, plan)


def test_container_owner_requires_container_type(plan, manifest):
    manifest["objects"][2]["item_type"] = "PICKABLE"
    with pytest.raises(ValueError, match="must be a CONTAINER"):
        validate_manifest(manifest, plan)


def test_start_scene_order_and_exits_cannot_drift(plan, manifest):
    manifest["scenes"].reverse()
    with pytest.raises(ValueError, match="scene order"):
        validate_manifest(manifest, plan)
    manifest["scenes"].reverse()
    manifest["exits"][0]["is_locked"] = True
    with pytest.raises(ValueError, match="planned exits"):
        validate_manifest(manifest, plan)


def test_award_identity_uses_key_and_title(plan, manifest):
    plan["awards"] = [{"id": "AWARD", "name": "Награда", "summary": "A discovery"}]
    manifest["awards"] = [{"key": "AWARD", "title": "Награда", "required_item_id": "KEY"}]
    validate_manifest(manifest, plan)


def test_switch_gate_and_target_references(plan, manifest):
    row = manifest["objects"][0]
    row["switch_transitions"] = [{"gates": {"item": "GHOST"}}]
    with pytest.raises(ValueError, match="gates.item"):
        validate_batch("objects", [row], plan)
    row.pop("switch_transitions")
    row["switch_outcomes"] = [{"effects": [{"type": "unlock_container", "target_id": "GHOST"}]}]
    with pytest.raises(ValueError, match="unlock_container.target_id"):
        validate_batch("objects", [row], plan)


def test_vn_empty_progression_is_valid(plan, manifest):
    manifest["rule_enforcement_mode"] = "vn"
    validate_manifest(manifest, plan)


@pytest.mark.parametrize("kind", ["protagonist", "npcs", "objects"])
def test_batch_ownership_checked_before_checkpoint(plan, manifest, kind):
    if kind == "protagonist":
        row = manifest[kind]
        row["starting_inventory"].append("LETTER")
        rows = row
    else:
        rows = manifest[kind]
        rows[0]["inventory"].append("KEY")
    with pytest.raises(ValueError, match="planned owner"):
        validate_batch(kind, rows, plan)


def test_npc_cannot_equip_another_owners_item(plan, manifest):
    manifest["npcs"][0]["equipped_weapon_id"] = "KEY"
    with pytest.raises(ValueError, match="planned owner"):
        validate_batch("npcs", manifest["npcs"], plan)


def test_container_batch_must_use_container_type(plan, manifest):
    row = manifest["objects"][2]
    row["item_type"] = "PICKABLE"
    with pytest.raises(ValueError, match="must be a CONTAINER"):
        validate_batch("objects", [row], plan)


def test_sequence_order_frozen_before_checkpoint(plan):
    plan["sequences"] = [
        {"id": "SEQ_A", "name": "Arrival"},
        {"id": "SEQ_B", "name": "Discovery"},
    ]
    row = {"id": "SEQ_B", "title": "Discovery", "order": 1}
    with pytest.raises(ValueError, match="sequence order"):
        validate_batch("sequences", [row], plan)
    row["order"] = 2
    validate_batch("sequences", [row], plan)


def test_batch_item_type_cannot_change_from_plan(plan, manifest):
    plan["objects"][0]["item_type"] = "KEY"
    row = manifest["objects"][0]
    with pytest.raises(ValueError, match="planned item_type 'KEY'"):
        validate_batch("objects", [row], plan)
    row["item_type"] = "KEY"
    validate_batch("objects", [row], plan)


@pytest.mark.parametrize("object_index", [0, 1, 3])
def test_held_item_must_share_owner_start_scene(plan, object_index):
    item = plan["objects"][object_index]
    item["start_scene_id"] = "TAVERN" if item["start_scene_id"] == "CITY" else "CITY"
    with pytest.raises(ValueError, match="owner's planned scene"):
        validate_plan(plan)


def test_nested_container_locations_follow_outer_owner(plan):
    plan["objects"][2]["owner_id"] = "LENA"
    validate_plan(plan)
    plan["npcs"][0]["start_scene_id"] = "CITY"
    plan["objects"][1]["start_scene_id"] = "CITY"
    plan["objects"][2]["start_scene_id"] = "CITY"
    with pytest.raises(ValueError, match="Object 'GEM'.*owner's planned scene"):
        validate_plan(plan)
    plan["objects"][3]["start_scene_id"] = "CITY"
    validate_plan(plan)
