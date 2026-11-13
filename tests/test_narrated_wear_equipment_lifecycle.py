"""Narrated wearable acquisition survives actual VN turns, slash commands and reload."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.stat_aggregator import calculate_total_stats
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_narrated_wear_equipment import ring
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

NARRATION = "Lina gives the hero a plain metal ring, and the hero puts it on."


async def seed_wear_fixture(db, created, slots):
    user, avatar, state, _ = await seed_vn(db)
    avatar.inventory = []
    avatar.equipment = {"Ring_1": None, "Ring_2": None}
    avatar.visual_profile = {"appearance": {"age_years": 30}, "worn": []}
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    note = {"id": "NOTE", "name": "Plain notebook", "description": "A small notebook."}
    npc.inventory = [note] if created else [note, ring(slots=slots)]
    npc.visual_profile = {"appearance": {"age_years": 30}, "worn": []}
    await db.commit()
    return user, avatar, state, note


@pytest.mark.parametrize("created", [False, True])
@pytest.mark.parametrize("slots", [["Ring_1"], ["Ring_1", "Ring_2"]])
async def test_saved_narrated_wear_and_slash_roundtrip_keep_one_canonical_item(
    monkeypatch, created, slots
):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)

    class WearRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if not issubclass(schema, ItemExtraction):
                return await super().structured(*args, **kwargs)
            identity = (
                {
                    "new_item": {
                        "name": "Plain ring",
                        "description": "A plain metal ring.",
                        "kind": "clothing",
                        "clothing": ring()["clothing"],
                        "wearable_slots": slots,
                    }
                }
                if created
                else {"item_id": "RING"}
            )
            self.calls.append((schema.__name__, args, kwargs))
            return extraction(
                schema,
                actions=[
                    ItemAction(
                        source_owner="LINA",
                        destination_owner=PLAYER,
                        disposition="worn",
                        basis="completed",
                        evidence=NARRATION,
                        **identity,
                    )
                ],
            )

    roles = WearRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, note = await seed_wear_fixture(db, created, slots)
        base_dexterity = calculate_total_stats(avatar)["dexterity"]
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Accept the ring and put it on.")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(avatar)
        await db.refresh(state)
        item = deepcopy(avatar.equipment["Ring_1"])
        assert item["name"] == "Plain ring"
        assert avatar.equipment["Ring_2"] is None
        assert avatar.inventory == []
        assert [row["item_id"] for row in avatar.visual_profile["worn"]] == [item["id"]]
        assert state.entity_states["LINA"]["inventory"] == [note]
        assert state.entity_states[KEY]["status"] == "complete"
        assert final_payload(chunks)["sheet"]["dexterity"] == base_dexterity + (0 if created else 3)
        avatar_id, user_id, session_id = avatar.id, user.id, state.session_id
    async with TestSessionLocal() as db:
        from backend.models.user import User

        user = await db.get(User, user_id)
        avatar = await db.get(Avatar, avatar_id)
        assert avatar.inventory == []
        assert avatar.equipment["Ring_1"] == item
        manager = GameTurnManager(db, session_id, user)
        chunks = [chunk async for chunk in manager.process_turn("/unequip Ring_1")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(avatar)
        assert avatar.inventory == [item]
        assert not any(
            value and value.get("id") == item["id"] for value in avatar.equipment.values()
        )
        assert final_payload(chunks)["sheet"]["dexterity"] == base_dexterity
        manager = GameTurnManager(db, session_id, user)
        chunks = [chunk async for chunk in manager.process_turn("/equip Plain ring")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(avatar)
        assert avatar.inventory == []
        assert avatar.equipment["Ring_1"] == item
        assert final_payload(chunks)["sheet"]["dexterity"] == base_dexterity + (0 if created else 3)
        assert len(roles.calls) == 3
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, avatar_id)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        assert avatar.inventory == []
        assert avatar.equipment["Ring_1"] == item
        assert state.entity_states["LINA"]["inventory"] == [note]
