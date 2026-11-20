"""Partial wardrobe facts retain unknown and known placement across real storage."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.sessions import copy_session
from backend.core.config import settings
from backend.engine import turn_controls
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.debug_wardrobe import WardrobeAction
from backend.engine.clothing.debug_wardrobe import apply as debug_placement
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.projection import item_wear_state, known_worn_item_ids
from backend.engine.clothing.schema import MAX_UNASSESSED_WEAR_ITEMS
from backend.engine.clothing.visuals import session_objects
from backend.engine.debug_npc_tools import WardrobeEdit, _edit_clothing
from backend.engine.export_archives import pack_export_ads
from backend.engine.npc_actions.contracts import Give, PutDown, Take, Wear
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_npc_carried_command_receipts import preview, stored_fixture

OLD_COAT = {
    "id": "OLD_COAT",
    "name": "Old coat",
    "clothing": {"layer": 1, "coverage": ["torso", "arms"]},
}


async def _world(db):
    host, drafts = await stored_fixture(db)
    observed = drafts["LINA"].scope.observation
    host.state.entity_states = {
        **host.state.entity_states,
        "LINA": {
            **host.state.entity_states.get("LINA", {}),
            "inventory": [*drafts["LINA"].scope.actors["LINA"]["inventory"], deepcopy(OLD_COAT)],
            "visual_profile": None,
        },
    }
    await db.commit()
    views = await capture_views(host, ["LINA", "SECOND"], observed)
    return host, observed, (await capture(host, views, observed))["LINA"]


def test_one_item_wear_does_not_establish_other_garments_as_carried():
    draft = preview()
    request = Give(tool="give_item", item_id="COAT", recipient_id="other")
    assert draft.execute(request)["reason_code"] == "unknown_wear_state"
    assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
    assert draft.execute(Wear(tool="wear_item", item_id="LOOSE_COAT"))["status"] == "staged"
    result = draft.execute(request)
    assert result["status"] == "blocked" and result["reason_code"] == "unknown_wear_state"
    assert draft.working_copy()[1].owners["COAT"] == "npc"


async def test_publication_keeps_unassessed_garment_custody_after_another_item_is_worn():
    async with TestSessionLocal() as db:
        host, _, draft = await _world(db)
        request = Give(tool="give_item", item_id="OLD_COAT", recipient_id="SECOND")
        assert draft.execute(request)["reason_code"] == "unknown_wear_state"
        assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
        assert draft.execute(Wear(tool="wear_item", item_id="LOOSE_COAT"))["status"] == "staged"
        draft.execute(request)
        draft.approved = True
        await publish(host, draft)
        await db.commit()
        await db.refresh(host.state)
        current = possession_snapshot(host, await session_objects(db, host.game_id))
        assert current.owners["OLD_COAT"] == "LINA"


async def test_carried_garment_survives_fresh_session_load_and_next_saved_input():
    async with TestSessionLocal() as db:
        host, previous, draft = await _world(db)
        assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
        draft.approved = True
        receipt = (await publish(host, draft))[0]
        assert receipt["status"] == "applied" and receipt["effect"]["disposition"] == "carried"
        await db.commit()
        session_id = host.game_id
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, session_id)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        avatar = await db.get(Avatar, game.avatar_id)
        message = ChatMessage(
            session_id=session_id,
            role="user",
            content="I wait again.",
            scene_id=state.current_scene_id,
        )
        db.add(message)
        await db.commit()
        host = SimpleNamespace(db=db, game_id=session_id, state=state, avatar=avatar)
        host._vn_player_message_id = message.id
        turn_controls.begin(host)
        turn_controls.bind_input(host, message)
        observed = previous.model_copy(
            update={
                "message_id": message.id,
                "revision_id": message.revision_id,
                "content_hash": sha256(message.content.encode()).hexdigest(),
                "player_request": message.content,
            }
        )
        views = await capture_views(host, ["LINA", "SECOND"], observed)
        current = (await capture(host, views, observed))["LINA"]
        assert current.scope.actors["LINA"]["visual_profile"]["wear_assessment_complete"] is False
        result = current.execute(PutDown(tool="put_down_item", item_id="LOOSE_COAT"))
        assert result["status"] == "staged", result
        blocked = current.execute(Give(tool="give_item", item_id="OLD_COAT", recipient_id="SECOND"))
        assert blocked["reason_code"] == "unknown_wear_state"
        current.approved = True
        assert (await publish(host, current))[0]["status"] == "applied"
        await db.commit()
        snapshot = possession_snapshot(host, await session_objects(db, session_id))
        assert snapshot.owners["LOOSE_COAT"] == "__scene__"
        assert snapshot.owners["OLD_COAT"] == "LINA"


async def _roundtrip(db, host, operation):
    game = await db.get(GameSession, host.game_id)
    user = await db.get(User, game.user_id)
    if operation == "copy":
        return (await copy_session(host.game_id, db, user))["game_id"]
    if operation == "ads":
        manifest = await SessionExporter.build_session_manifest(db, host.game_id)
        return await SessionImporter.import_ads(
            db, pack_export_ads(manifest, host.game_id), user.id
        )
    checkpoint = await SessionCheckpointService.create_checkpoint(db, host.game_id, "manual")
    await db.commit()
    changed = deepcopy(host.state.entity_states)
    changed["LINA"]["visual_profile"] = {"worn": []}
    host.state.entity_states = changed
    await db.commit()
    await SessionCheckpointService.restore_checkpoint(db, host.game_id, checkpoint.id)
    await db.commit()
    return host.game_id


@pytest.mark.parametrize("operation", ["copy", "ads", "checkpoint"])
async def test_partial_known_and_unknown_placements_survive_existing_portability(
    operation, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        host, _, draft = await _world(db)
        assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
        draft.approved = True
        assert (await publish(host, draft))[0]["status"] == "applied"
        await db.commit()
        target = await _roundtrip(db, host, operation)
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, target)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == target))
        avatar = await db.get(Avatar, game.avatar_id)
        host = SimpleNamespace(db=db, game_id=target, state=state, avatar=avatar)
        actor = actor_records(host, await session_objects(db, target))["LINA"]
        raw, items = actor["visual_profile"], actor["resolved_inventory"]
        assert raw["wear_assessment_complete"] is False
        assert item_wear_state(raw, items, "LOOSE_COAT") == "carried"
        assert item_wear_state(raw, items, "OLD_COAT") == "unknown"
        assert known_worn_item_ids(raw, items) is None


@pytest.mark.parametrize("path", ["placement", "edit"])
async def test_explicit_debug_changes_resolve_only_the_selected_existing_garment(path):
    async with TestSessionLocal() as db:
        host, _, _ = await _world(db)
        if path == "placement":
            await debug_placement(
                db,
                host.state,
                host.avatar,
                WardrobeAction(npc_id="LINA", item_id="OLD_COAT", operation="wear"),
            )
        else:
            await _edit_clothing(
                db,
                host.state,
                WardrobeEdit(
                    npc_id="LINA",
                    item_id="OLD_COAT",
                    name="Old coat",
                    description="A familiar coat.",
                    clothing=OLD_COAT["clothing"],
                    worn=True,
                ),
            )
        await db.commit()
        await db.refresh(host.state)
        actor = actor_records(host, await session_objects(db, host.game_id))["LINA"]
        raw, items = actor["visual_profile"], actor["resolved_inventory"]
        assert item_wear_state(raw, items, "OLD_COAT") == "worn"
        assert item_wear_state(raw, items, "UNASSESSED_COAT") == "unknown"
        assert known_worn_item_ids(raw, items) is None


@pytest.mark.parametrize(
    ("count", "complete", "allowed"), [(128, False, True), (129, False, False), (129, True, True)]
)
async def test_partial_capacity_publication_and_fresh_load_share_the_same_bound(
    count, complete, allowed
):
    async with TestSessionLocal() as db:
        host, observed, _ = await _world(db)
        inventory = [{**deepcopy(OLD_COAT), "id": f"GARMENT_{index}"} for index in range(count)]
        states = deepcopy(host.state.entity_states)
        states["LINA"].update(
            inventory=inventory, visual_profile={"worn": []} if complete else None
        )
        host.state.entity_states = states
        await db.commit()
        views = await capture_views(host, ["LINA"], observed)
        draft = (await capture(host, views, observed))["LINA"]
        before = deepcopy(host.state.entity_states)
        result = draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))
        assert (result["status"] == "staged") is allowed
        assert host.state.entity_states == before
        draft.approved = True
        results = await publish(host, draft)
        assert len(results) == int(allowed)
        await db.commit()
        identifier = host.game_id
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == identifier))
        raw = state.entity_states["LINA"]["visual_profile"]
        if allowed:
            profile = load_profile(raw)
            assert profile is not None
            assert len(profile.unassessed_wear_item_ids) == (
                0 if complete else MAX_UNASSESSED_WEAR_ITEMS
            )
        else:
            assert raw is None and state.entity_states["LINA"]["inventory"] == inventory
