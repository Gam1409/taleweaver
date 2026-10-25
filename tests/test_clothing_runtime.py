"""Wardrobe changes conserve possessions and require grounded, completed outcomes."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_helpers import TurnProgressionBuilder
from backend.engine.clothing.actions import GarmentCreation, WardrobeAction
from backend.engine.clothing.context import build_clothing_context
from backend.engine.clothing.planning import validate_plan
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.llm_intents import ChatProgressionIntent, MechanicsIntent
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.continuity import PLAYER, prepare_intent
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

GARMENT = {"layer": 2, "coverage": ["torso", "arms"], "opaque": True}
ACTION = "I put on my blue coat."


def item(identifier="coat", name="Blue coat"):
    return {"id": identifier, "name": name, "description": "A warm coat.", "clothing": GARMENT}


def profile(*ids):
    return {
        "version": 1,
        "appearance": {"age_years": 30, "hair": "black"},
        "worn": [{"item_id": identifier} for identifier in ids],
    }


def world():
    npc = SimpleNamespace(
        id="ANNA",
        name="Anna",
        entity_type="NPC",
        session_id="S",
        current_scene_id="ROOM",
        is_hidden=False,
        is_defeated=False,
        is_in_inventory=False,
        description="Anna owns the clothing shop.",
        inventory=[item("hat", "Green hat")],
        visual_profile=profile("hat"),
        metadata_json={},
        character="Independent.",
        goal="Keep the shop open.",
    )
    manager = SimpleNamespace(
        _vn_player_message_id="M1",
        state=SimpleNamespace(session_id="S", current_scene_id="ROOM", entity_states={}),
        avatar=SimpleNamespace(
            id="AV",
            name="Player",
            description="A traveler.",
            inventory=[item()],
            equipment={},
            visual_profile=profile(),
        ),
        db=SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [npc]))),
    )
    return (
        manager,
        npc,
        [{"id": "ROOM", "description": "An established clothing shop with an open wardrobe."}],
    )


def action(**changes):
    return WardrobeAction(
        **(
            {
                "actor_id": PLAYER,
                "source": "player_action",
                "evidence": ACTION,
                "basis": "performed",
                "agency": "self_action",
                "reason": "The player puts on their owned coat.",
                "item_id": "coat",
                "operation": "wear",
            }
            | changes
        )
    )


def creation(**changes):
    return GarmentCreation(
        **(
            {
                "actor_id": PLAYER,
                "source": "player_action",
                "evidence": "I buy a red scarf.",
                "basis": "performed",
                "agency": "self_action",
                "reason": "A purchase is completed at the established shop.",
                "acquisition": "shop",
                "source_id": "ROOM",
                "source_evidence": "An established clothing shop",
                "name": "Red scarf",
                "clothing": {"layer": 3, "coverage": ["torso"]},
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "basis", ["claim", "past", "future", "hypothetical", "negated", "uncertain"]
)
def test_non_completed_acquisitions_and_wear_are_rejected(basis):
    manager, npc, scenes = world()
    proposal = VNProgressionIntent(
        wardrobe_actions=[action(basis=basis)], garment_creations=[creation(basis=basis)]
    )
    plan = validate_plan(manager, proposal, ACTION + " I buy a red scarf.", "", [npc], scenes)
    assert not plan.actions and not plan.creations
    assert len(plan.errors) == 2


@pytest.mark.parametrize(
    "source_id, evidence",
    [
        ("INVENTED_SHOP", "An established clothing shop"),
        ("ROOM", "An invented wardrobe in my backpack"),
    ],
)
def test_invented_shop_or_wardrobe_has_no_available_source(source_id, evidence):
    manager, npc, scenes = world()
    proposal = VNProgressionIntent(
        garment_creations=[creation(source_id=source_id, source_evidence=evidence)]
    )
    assert not validate_plan(manager, proposal, "I buy a red scarf.", "", [npc], scenes).creations


def test_player_assertion_cannot_approve_npc_wear_and_existing_gifts_cannot_be_minted():
    manager, npc, scenes = world()
    forced = action(
        actor_id="ANNA",
        item_id="hat",
        agency="npc_choice",
        evidence="I force Anna to wear the hat.",
    )
    proposal = VNProgressionIntent(
        wardrobe_actions=[forced],
        garment_creations=[
            creation(
                name="Green hat",
                acquisition="gift",
                source_id="ANNA",
                source_evidence="Anna owns the clothing shop.",
            )
        ],
    )
    plan = validate_plan(
        manager, proposal, forced.evidence + " I buy a red scarf.", "", [npc], scenes
    )
    assert not plan.actions and not plan.creations
    with pytest.raises(ValidationError):
        creation(acquisition="theft")


@pytest.mark.asyncio
async def test_wear_adjust_remove_preserves_items_and_rejects_impossible_region():
    manager, npc, scenes = world()
    before = deepcopy(manager.avatar.inventory)
    for number, operation, regions in [
        (1, "wear", []),
        (2, "adjust", ["arms"]),
        (3, "adjust", ["feet"]),
        (4, "remove", []),
    ]:
        manager._vn_player_message_id = f"M{number}"
        event = GameEvent()
        event._vn_clothing_plan = validate_plan(
            manager,
            VNProgressionIntent(
                wardrobe_actions=[action(operation=operation, uncovered_regions=regions)]
            ),
            ACTION,
            "",
            [npc],
            scenes,
        )
        await apply_wardrobe(manager, event, manager.state.entity_states)
        if number == 3:
            assert manager.avatar.visual_profile["worn"][0]["uncovered_regions"] == ["arms"]
            assert "not_completed" in event.narrative_description
    assert manager.avatar.visual_profile["worn"] == []
    assert manager.avatar.inventory == before


@pytest.mark.asyncio
async def test_grounded_creation_mints_one_cosmetic_item_and_replay_is_idempotent():
    manager, npc, scenes = world()
    made = creation(wear=True)
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(
        manager, VNProgressionIntent(garment_creations=[made]), made.evidence, "", [npc], scenes
    )
    await apply_wardrobe(manager, event, manager.state.entity_states)
    await apply_wardrobe(manager, event, manager.state.entity_states)
    assert len(manager.avatar.inventory) == 2
    created = manager.avatar.inventory[-1]
    assert created["id"].startswith("garment_")
    assert created["clothing_origin"]["source_message_id"] == "M1"
    assert manager.avatar.visual_profile["worn"][0]["item_id"] == created["id"]
    assert not set(created) & {"hp_change", "stat_modifier_armor_class", "price"}
    assert npc.visual_profile == profile("hat")


def test_empty_backpack_and_rebranding_cannot_create_an_absent_weapon():
    manager, npc, _scenes = world()
    manager.avatar.inventory = []
    fabricated = prepare_intent(
        manager, {"new_inventory_items": [{"id": "HUGE_AXE", "name": "Huge axe"}]}, [npc]
    )
    assert not fabricated.new_inventory_items
    manager.avatar.inventory = [
        {"id": "pencil", "name": "Pencil", "description": "A small pencil."}
    ]
    renamed = prepare_intent(
        manager,
        {
            "updated_inventory_items": [
                {
                    "id": "pencil",
                    "name": "Huge axe",
                    "description": "A lethal battle axe.",
                    "condition_note": "The tip is chipped.",
                }
            ]
        },
        [npc],
    )
    updated = renamed.updated_inventory_items[0]
    assert updated.name == "Pencil" and updated.description == "A small pencil."
    assert updated.condition_note == "The tip is chipped."
    assert "identity" in renamed.narrative_description


def test_stale_equipment_string_cannot_claim_someone_elses_garment():
    manager, npc, _scenes = world()
    manager.avatar.equipment = {"Head": "hat"}
    result = prepare_intent(
        manager,
        {"removed_inventory_item_ids": ["hat"], "spawned_items": [{"id": "hat", "name": "Hat"}]},
        [npc],
    )
    assert not result.spawned_items and not result.removed_inventory_item_ids


@pytest.mark.asyncio
async def test_successful_theft_moves_existing_worn_id_and_failed_theft_changes_nothing():
    manager, npc, _scenes = world()
    empty = GameEvent()
    before = deepcopy(npc.inventory)
    await apply_wardrobe(manager, empty, manager.state.entity_states)
    assert npc.inventory == before and npc.visual_profile == profile("hat")
    intent = prepare_intent(manager, {"new_inventory_items": [{"id": "hat", "name": "Hat"}]}, [npc])
    assert intent.new_inventory_items[0].id == "hat"
    assert intent.updated_entities[0].inventory == []
    manager.avatar.inventory.append(intent.new_inventory_items[0].model_dump(exclude_none=True))
    manager.state.entity_states["ANNA"] = {"inventory": []}
    await apply_wardrobe(manager, GameEvent(), manager.state.entity_states)
    assert manager.state.entity_states["ANNA"]["visual_profile"]["worn"] == []
    assert [i["id"] for i in manager.avatar.inventory].count("hat") == 1


def test_wardrobe_schema_does_not_expand_legacy_modes_or_expose_private_plan():
    assert "wardrobe_actions" in VNProgressionIntent.model_fields
    assert "wardrobe_actions" not in ChatProgressionIntent.model_fields
    assert "wardrobe_actions" not in MechanicsIntent.model_fields
    assert "_vn_clothing_plan" not in GameEvent().model_dump()


class ClothingRoles(TurnRoles):
    def __init__(self):
        super().__init__()
        self.change = True

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent") and self.change:
            result.wardrobe_actions = [action()]
        return result


@pytest.mark.asyncio
async def test_real_turn_updates_narrator_and_next_turn_without_extra_llm_calls(monkeypatch):
    roles = ClothingRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _source = await seed_vn(db)
        avatar.inventory, avatar.visual_profile = [item()], profile()
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "LINA", WorldEntity.session_id == "session-1"
            )
        )
        npc.description = "OLD_BIO_OUTFIT with HIDDEN_UNDERLAYER."
        npc.inventory = [
            item("NPC_COAT", "Current visible coat"),
            {
                "id": "PRIVATE_UNDER",
                "name": "HIDDEN_UNDERLAYER",
                "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
            },
        ]
        npc.visual_profile = profile("NPC_COAT", "PRIVATE_UNDER")
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        first = [chunk async for chunk in manager.process_turn(ACTION)]
        assert not any(chunk.startswith("event: error") for chunk in first), "".join(first)
        assert avatar.visual_profile["worn"][0]["item_id"] == "coat"
        assert "Blue coat" in str(roles.prompts[-1])
        assert "AUTHORITATIVE CURRENT APPEARANCE" in str(roles.prompts[-1])
        assert "Current visible coat" in str(roles.prompts[-1])
        assert "HIDDEN_UNDERLAYER" not in str(roles.prompts[-1])
        assert "OLD_BIO_OUTFIT" not in str(roles.prompts[-1])
        assert len(roles.calls) == 2
        roles.change = False
        second = [chunk async for chunk in manager.process_turn("Tell me about the town.")]
        assert not any(chunk.startswith("event: error") for chunk in second), "".join(second)
        assert "Blue coat" in str(roles.prompts[-1])
        assert len(roles.calls) == 4
        context = build_clothing_context(manager, [], [])
        assert context["actors"][0]["visual_profile"]["worn"][0]["item_id"] == "coat"


@pytest.mark.asyncio
async def test_real_equipped_gift_then_npc_drop_keeps_one_id_and_metadata(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state, _source = await seed_vn(db)
        coat = item()
        coat["clothing_origin"] = {
            "kind": "runtime",
            "session_id": "session-1",
            "source_message_id": "existing",
        }
        avatar.inventory, avatar.equipment, avatar.visual_profile = (
            [],
            {"Body": coat},
            profile("coat"),
        )
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        await manager.initialize()
        entities = list(
            (
                await db.scalars(select(WorldEntity).where(WorldEntity.session_id == "session-1"))
            ).all()
        )
        gift = prepare_intent(
            manager,
            {
                "updated_entities": [
                    {"entity_id": "LINA", "inventory": [{"id": "coat", "name": "Coat"}]}
                ]
            },
            entities,
        )
        await manager._apply_game_event(TurnProgressionBuilder.build_progression_event(gift))
        assert avatar.visual_profile["worn"] == []
        assert not avatar.inventory and not any(avatar.equipment.values())
        npc_inventory = state.entity_states["LINA"]["inventory"]
        assert next(i for i in npc_inventory if i["id"] == "coat")["clothing"] == coat["clothing"]
        assert not state.entity_states["LINA"].get("visual_profile")
        dropped = prepare_intent(
            manager, {"spawned_items": [{"id": "coat", "name": "Coat"}]}, entities
        )
        await manager._apply_game_event(TurnProgressionBuilder.build_progression_event(dropped))
        await db.flush()
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "coat", WorldEntity.session_id == "session-1"
            )
        )
        assert row.metadata_json["clothing"] == coat["clothing"]
        assert row.metadata_json["clothing_origin"] == coat["clothing_origin"]
        assert {i["id"] for i in state.entity_states["LINA"]["inventory"]} == {"HIDDEN_RING"}
