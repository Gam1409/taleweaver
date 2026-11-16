"""Keep import-format defaults and world ownership rules distinct during refactoring."""

from copy import deepcopy
from types import SimpleNamespace

from backend.engine.adventure_export_assets import normalize_exported_equipment
from backend.engine.import_build_archive_template import build_archive_template
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.import_build_session_template import build_session_template
from backend.engine.world_generator import WorldGenerator, _ensure_containers_have_minimum_inventory


def test_import_formats_keep_distinct_defaults_and_explicit_false_values():
    adventure = {
        "title": "Import contract",
        "min_items": 0,
        "max_memory_turns": 0,
        "starting_timestamp": 0,
        "can_damage_npcs": False,
    }
    payload = {
        "adventure": adventure,
        "min_items": 9,
        "max_memory_turns": 7,
        "starting_timestamp": 99,
        "can_damage_npcs": True,
    }
    archive = build_archive_template(
        "template", "owner", adventure, payload, None, "rpg", True, None, None
    )
    blueprint = build_blueprint_template(payload, payload, adventure, "owner", None, "rpg", True)
    session = build_session_template(payload, SimpleNamespace(id="owner"), None)

    assert [item.time_per_turn for item in (archive, blueprint, session)] == [5, 5, 10]
    assert [item.max_memory_turns for item in (archive, blueprint, session)] == [7, 7, 10]
    assert [item.starting_timestamp for item in (archive, blueprint, session)] == [99, 99, 0]
    for template in (archive, blueprint, session):
        assert template.min_items == 0
        assert template.can_damage_npcs is False


def test_export_prioritizes_scene_then_inventory_then_equipment_without_mutation():
    avatar = SimpleNamespace(
        inventory=[{"id": "SCENE_ITEM"}, {"id": "BAG_ITEM"}, "BAG_ITEM", None],
        equipment={"hand": "BAG_ITEM", "body": {"id": "COAT"}, "head": "COAT"},
    )
    entities = [SimpleNamespace(entity_type="OBJECT", id="SCENE_ITEM", current_scene_id="ROOM")]
    before = deepcopy(vars(avatar))

    inventory, equipment = normalize_exported_equipment(avatar, entities)

    assert inventory == ["BAG_ITEM"]
    assert equipment == {"body": "COAT"}
    assert vars(avatar) == before


def test_object_annotation_leaves_technical_references_and_unrelated_fields_intact():
    manifest = {
        "objects": [{"id": "KEY_1", "description": "Use KEY_1", "name": "KEY_1"}],
        "scenes": [{"id": "ROOM", "description": "Take key_1", "label": "KEY_1"}],
        "sequences": [{"title": "KEY_1", "required_item_id": "##key_1"}],
    }

    WorldGenerator.preprocess_manifest_object_ids(manifest)

    assert manifest["objects"][0] == {"id": "KEY_1", "description": "Use ##KEY_1", "name": "KEY_1"}
    assert manifest["scenes"][0]["description"] == "Take ##KEY_1"
    assert manifest["scenes"][0]["label"] == "KEY_1"
    assert manifest["sequences"][0]["title"] == "##KEY_1"
    assert manifest["sequences"][0]["required_item_id"] == "KEY_1"


def test_container_population_keeps_existing_ownership_and_never_invents_items():
    objects = [
        {"id": "BOX_A", "item_type": "CONTAINER", "inventory": ["ITEM_A", "ITEM_A", "MISSING"]},
        {"id": "BOX_B", "item_type": "CONTAINER", "inventory": ["BOX_B"]},
        {"id": "BOX_C", "item_type": "CONTAINER"},
        {"id": "ITEM_A", "item_type": "PICKABLE"},
        {"id": "ITEM_B", "item_type": "PICKABLE"},
    ]

    _ensure_containers_have_minimum_inventory(objects)

    assert [item["inventory"] for item in objects[:3]] == [["ITEM_A"], ["ITEM_B"], []]
