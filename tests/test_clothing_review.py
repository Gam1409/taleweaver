"""Independent clothing integration regressions for frozen preferences and rewind."""

from copy import deepcopy

from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.turn_helpers import TurnProgressionBuilder
from backend.engine.clothing.actions import GarmentCreation
from backend.engine.clothing.planning import WardrobePlan
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.rule_engine import GameEvent
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.visual_novel.continuity import PLAYER, prepare_intent
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
SESSION = "portrait-session"


def profile(identifier="COAT"):
    return {
        "version": 1,
        "appearance": {"age_years": 30, "hair": "Brown"},
        "worn": [{"item_id": identifier}],
    }


def garment(identifier="COAT", *, underwear=False):
    return {
        "id": identifier,
        "name": identifier,
        "description": "A neutral garment",
        "clothing": {
            "layer": 1,
            "coverage": ["torso"],
            "opaque": True,
            "underwear": underwear,
            "description": "Plain fabric",
        },
    }


async def context(db):
    state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
    avatar = await db.get(Avatar, state.avatar_id)
    return state, avatar


async def test_sheet_legacy_snapshot_never_adopts_live_template_detail_setting(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        state, avatar = await context(db)
        template = await db.get(AdventureTemplate, state.template_id)
        template.original_manifest = {"clothing_settings": {"detailed": True}}
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {"original_manifest": {}},
        }
        avatar.visual_profile = profile("PRIVATE_UNDERLAYER")
        avatar.inventory = [garment("PRIVATE_UNDERLAYER", underwear=True)]
        await db.commit()
        sheet = await AdventureLogic.build_sheet_snapshot(avatar, state, db)
        assert sheet["clothing"]["worn"] == []
        assert sheet["clothing"]["detail_limited"] is True


async def test_restore_pre_feature_checkpoint_clears_future_visual_profile(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        state, avatar = await context(db)
        checkpoint = await SessionCheckpointService.create_checkpoint(db, SESSION, "manual")
        snapshot = deepcopy(checkpoint.state_snapshot)
        snapshot["avatar"].pop("visual_profile")
        checkpoint.state_snapshot = snapshot
        await db.commit()
        avatar.visual_profile = profile()
        avatar.inventory = [garment()]
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, SESSION, checkpoint.id)
        await db.commit()
        assert avatar.inventory == []
        assert avatar.visual_profile is None


async def test_rewind_removes_created_then_dropped_garment_from_world(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        state, avatar = await context(db)
        template = await db.get(AdventureTemplate, state.template_id)
        template.rule_enforcement_mode = "vn"
        await db.commit()
        user = await db.get(User, avatar.user_id)
        manager = GameTurnManager(db, SESSION, user)
        await manager.initialize()
        checkpoint = await SessionCheckpointService.create_checkpoint(db, SESSION, "manual")
        await db.commit()
        source = ChatMessage(
            id="clothing-after-checkpoint",
            session_id=SESSION,
            role="user",
            content="I take a coat from the wardrobe.",
            scene_id=state.current_scene_id,
        )
        db.add(source)
        await db.flush()
        creation = GarmentCreation(
            actor_id=PLAYER,
            source="player_action",
            evidence=source.content,
            basis="performed",
            agency="self_action",
            reason="The accessible wardrobe contains ordinary clothing.",
            acquisition="wardrobe",
            source_id=state.current_scene_id,
            source_evidence="An accessible wardrobe with ordinary clothing.",
            name="Travel coat",
            clothing=garment()["clothing"],
            wear=False,
        )
        event = GameEvent()
        event._vn_clothing_plan = WardrobePlan(
            source.id, state.current_scene_id, creations=[creation]
        )
        states = deepcopy(state.entity_states)
        await apply_wardrobe(manager, event, states)
        state.entity_states = states
        created = deepcopy(avatar.inventory[-1])
        assert created["id"].startswith("garment_")
        await db.commit()
        entities = list(
            (await db.scalars(select(WorldEntity).where(WorldEntity.session_id == SESSION))).all()
        )
        intent = prepare_intent(
            manager,
            {"spawned_items": [{"id": created["id"], "name": "Untrusted model label"}]},
            entities,
        )
        # The production boundary restores provenance from the canonical possession.
        drop = TurnProgressionBuilder.build_progression_event(intent)
        assert drop.spawned_items[0].model_dump()["clothing_origin"] == created["clothing_origin"]
        await manager._apply_game_event(drop)
        await db.commit()
        assert await db.scalar(
            select(WorldEntity.pk).where(
                WorldEntity.session_id == SESSION, WorldEntity.id == created["id"]
            )
        )
        await SessionCheckpointService.restore_checkpoint(db, SESSION, checkpoint.id)
        await db.commit()
        entities = await AdventureLogic.build_session_entities(db, state)
        assert created["id"] not in {entity["id"] for entity in entities}
        assert avatar.inventory == []
