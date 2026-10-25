"""VN transfers preserve authoritative possessions and never manufacture item IDs."""

from copy import deepcopy
from types import SimpleNamespace

from backend.api.routes.adventures.turn_helpers import TurnProgressionBuilder
from backend.engine.visual_novel.continuity import prepare_intent
from backend.engine.visual_novel.intent import build_progression_context


def entity(entity_id, *, kind="NPC", inventory=None, **kwargs):
    return SimpleNamespace(
        id=entity_id,
        name=entity_id,
        entity_type=kind,
        session_id="session",
        current_scene_id="ROOM",
        is_hidden=False,
        is_in_inventory=False,
        inventory=inventory or [],
        metadata_json={},
        **kwargs,
    )


def manager(inventory=None, overrides=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            current_scene_id="ROOM",
            session_id="session",
            entity_states=overrides or {},
            in_game_time=10,
        ),
        avatar=SimpleNamespace(inventory=inventory or []),
        _get_gm_notes=lambda: [],
    )


def test_player_gift_preserves_metadata_and_pairs_ownership_changes():
    ring = {
        "id": "ring",
        "name": "Family ring",
        "image_url": "/data/ring.png",
        "stat_modifier_charisma": 2,
        "wearable_slots": ["Finger"],
        "provenance": "A keepsake",
    }
    book = {"id": "book", "name": "Diary", "image_url": "/data/diary.png", "hp_change": 3}
    owner = manager([ring])
    npc = entity("anna", inventory=[book])
    before = deepcopy(owner.avatar.inventory)

    intent = prepare_intent(
        owner,
        {
            "updated_entities": [
                {
                    "entity_id": "anna",
                    "inventory": [
                        {"id": "ring", "name": "Forged name", "stat_modifier_charisma": 999}
                    ],
                }
            ]
        },
        [npc],
    )
    event = TurnProgressionBuilder.build_progression_event(intent)

    assert event.removed_inventory_item_ids == ["ring"]
    items = {item.id: item for item in event.updated_entities[0].inventory}
    assert items["ring"].model_dump(exclude_none=True) == ring
    assert items["book"].model_dump(exclude_none=True) == book
    assert owner.avatar.inventory == before


def test_player_pickup_preserves_world_image_stats_and_effects():
    potion = entity(
        "potion",
        kind="OBJECT",
        image_url="/data/potion.png",
        description="A small vial",
        item_type="CONSUMABLE",
        stat_modifier_wisdom=2,
    )
    potion.metadata_json = {"hp_change": 7, "mana_change": 4}
    intent = prepare_intent(
        manager(),
        {"new_inventory_items": [{"id": "potion", "name": "Made up", "hp_change": 999}]},
        [potion],
    )
    event = TurnProgressionBuilder.build_progression_event(intent)
    item = event.new_inventory_items[0]
    assert item.id == "potion" and item.name == "potion"
    assert item.image_url == "/data/potion.png" and item.stat_modifier_wisdom == 2
    assert item.hp_change == 7 and item.mana_change == 4


def test_npc_gift_uses_override_inventory_and_preserves_its_other_items():
    current = [
        {"id": "key", "name": "Current key", "image_url": "/data/key.png"},
        {"id": "note", "name": "Note"},
    ]
    owner = manager(overrides={"anna": {"inventory": current}})
    npc = entity("anna", inventory=[{"id": "stale", "name": "Already lost"}])
    intent = prepare_intent(owner, {"new_inventory_items": [{"id": "key", "name": "key"}]}, [npc])
    assert intent.new_inventory_items[0].image_url == "/data/key.png"
    assert [item.id for item in intent.updated_entities[0].inventory] == ["note"]
    assert owner.state.entity_states["anna"]["inventory"] == current


def test_unknown_item_rejects_whole_transfer_batch_without_losing_player_item():
    owner = manager([{"id": "key", "name": "Key"}])
    intent = prepare_intent(
        owner,
        {
            "removed_inventory_item_ids": ["key"],
            "updated_entities": [
                {"entity_id": "anna", "inventory": [{"id": "invented", "name": "Key"}]}
            ],
            "new_inventory_items": [{"id": "also_invented", "name": "Treasure"}],
        },
        [entity("anna")],
    )
    assert not intent.new_inventory_items and not intent.removed_inventory_item_ids
    assert intent.updated_entities[0].inventory is None
    assert "did not occur" in intent.narrative_description
    assert owner.avatar.inventory == [{"id": "key", "name": "Key"}]


def test_unavailable_remote_and_contained_items_cannot_be_picked_up():
    remote = entity("remote", inventory=[{"id": "remote_key", "name": "Remote key"}])
    remote.current_scene_id = "ELSEWHERE"
    box = entity("box", kind="OBJECT", inventory=[{"id": "locked_key", "name": "Locked key"}])
    shadow = entity("locked_key", kind="OBJECT")
    foreign = entity("foreign_key", kind="OBJECT")
    foreign.session_id = "other_session"
    for item_id in ("remote_key", "locked_key", "foreign_key"):
        intent = prepare_intent(
            manager(),
            {"new_inventory_items": [{"id": item_id, "name": item_id}]},
            [remote, box, shadow, foreign],
        )
        assert not intent.new_inventory_items


def test_duplicate_and_conflicting_targets_do_not_clone_items():
    owner = manager([{"id": "key", "name": "Key", "item_type": "CONSUMABLE"}])
    duplicate = prepare_intent(owner, {"new_inventory_items": [{"id": "key", "name": "Key"}]}, [])
    assert not duplicate.new_inventory_items
    conflict = prepare_intent(
        owner,
        {
            "spawned_items": [{"id": "key", "name": "Key"}],
            "updated_entities": [
                {"entity_id": "anna", "inventory": [{"id": "key", "name": "Key"}]}
            ],
        },
        [entity("anna")],
    )
    assert not conflict.spawned_items and not conflict.removed_inventory_item_ids
    assert conflict.updated_entities[0].inventory is None


def test_ambiguous_removal_is_rejected_but_confirmed_consumption_is_retained():
    owner = manager([{"id": "potion", "name": "Potion", "hp_change": 7}])
    ambiguous = prepare_intent(owner, {"removed_inventory_item_ids": ["potion"]}, [])
    assert not ambiguous.removed_inventory_item_ids
    consumed = prepare_intent(
        owner, {"removed_inventory_item_ids": ["potion"], "deleted_entities": ["potion"]}, []
    )
    assert consumed.removed_inventory_item_ids == ["potion"]
    assert consumed.deleted_entities == ["potion"]


def test_context_hydrates_actual_inventory_and_excludes_possession_shadow_from_scene_items():
    import json

    npc = entity("anna", inventory=[{"id": "key", "name": "Key", "hp_change": 5}])
    shadow = entity("key", kind="OBJECT")
    loose = entity("flower", kind="OBJECT")
    context = build_progression_context(
        manager(),
        npcs=[],
        scenes=[{"id": "ROOM", "label": "Room"}],
        exits=[],
        entities=[npc, shadow, loose],
    )
    data = json.loads(context.split("\n", 1)[1])
    assert data["present_characters"][0]["inventory"] == [{"id": "key", "name": "Key"}]
    assert [item["id"] for item in data["scene_items"]] == ["flower"]


def test_unlocked_container_contents_are_available_but_fixed_container_is_not_portable():
    box = entity(
        "box",
        kind="OBJECT",
        inventory=[{"id": "key", "name": "Key", "image_url": "/data/key.png"}],
        item_type="CONTAINER",
        is_portable=False,
    )
    box.metadata_json = {"code_to_unlock": "123"}
    locked = prepare_intent(
        manager(), {"new_inventory_items": [{"id": "key", "name": "Key"}]}, [box]
    )
    assert not locked.new_inventory_items
    owner = manager(overrides={"box": {"locked": False}})
    opened = prepare_intent(owner, {"new_inventory_items": [{"id": "key", "name": "Key"}]}, [box])
    assert opened.new_inventory_items[0].image_url == "/data/key.png"
    assert opened.updated_entities[0].entity_id == "box"
    assert opened.updated_entities[0].inventory == []
    fixed = prepare_intent(owner, {"new_inventory_items": [{"id": "box", "name": "box"}]}, [box])
    assert not fixed.new_inventory_items
