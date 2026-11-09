"""A denied item action cannot suppress unrelated facts or establish its own result."""

from uuid import NAMESPACE_URL, uuid5

import pytest

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import reconcile_items
from backend.engine.physical_conditions.ledger import read as read_conditions
from backend.engine.physical_conditions.runtime import finish as finish_conditions
from backend.engine.scene_continuity.ledger import read
from backend.engine.scene_continuity.runtime import finish as finish_scene
from backend.engine.scene_staging import props
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_shared_scene_staging import SharedRoles, seed
from tests.test_vn_turn_integration import final_payload

TEXT = "The kettle starts boiling. Miki has blue ink on her hand. Hero holds a missing scarf."


class IndependentRoles(SharedRoles):
    actions = []
    staging = {"changes": [], "props": [], "explicit": []}
    denied = True

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent") and self.denied:
            result.removed_inventory_item_ids = ["NOT_OWNED"]
        if type(result).__name__ in {"SharedItemExtraction", "ItemExtraction"}:
            result.scene_updates = [
                {
                    "operation": "record",
                    "key": "boiling",
                    "subject_id": "KETTLE",
                    "detail": "The kettle is boiling.",
                    "visibility": "public",
                    "evidence": "The kettle starts boiling.",
                },
                {
                    "operation": "record",
                    "key": "missing-scarf",
                    "kind": "effect",
                    "subject_id": "__player__",
                    "detail": "Hero holds the missing scarf.",
                    "visibility": "public",
                    "evidence": "Hero holds a missing scarf.",
                },
            ]
            result.condition_updates = [
                {
                    "operation": "record",
                    "target_id": "MIKI",
                    "kind": "contamination",
                    "part": "hand",
                    "detail": "Blue ink on the hand",
                    "evidence": "Miki has blue ink on her hand.",
                }
            ]
        return result


@pytest.mark.parametrize("staging", [False, True])
async def test_local_item_denial_preserves_unrelated_process_and_body_fact(monkeypatch, staging):
    async with TestSessionLocal() as db:
        roles, user, avatar, state = await seed(
            monkeypatch, db, enabled=staging, roles=IndependentRoles()
        )
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
        before = list(avatar.inventory)
        db.add(
            WorldEntity(
                id="KETTLE",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Kettle",
                description="A kettle on a table.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        db.add(
            WorldEntity(
                id="MIKI",
                session_id=state.session_id,
                entity_type="NPC",
                name="Miki",
                description="An adult archivist.",
                current_scene_id="START",
                inventory=[],
                is_hidden=False,
            )
        )
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        assert avatar.inventory == before
        records = list(read(state.entity_states).records.values())
        assert [row.subject_id for row in records] == ["KETTLE"]
        assert any(
            row.target_id == "MIKI" and "ink" in row.detail
            for row in read_conditions(state.entity_states).conditions.values()
        )
        assert len(roles.calls) == 3


async def test_general_rule_denial_cannot_be_bypassed_by_a_bad_item_batch(monkeypatch):
    class BadBatch(IndependentRoles):
        denied = False
        actions = [{"item_id": "COAT", "source_owner": "LINA"}]

    async with TestSessionLocal() as db:
        _roles, user, _avatar, state = await seed(monkeypatch, db, roles=BadBatch())
        db.add(
            WorldEntity(
                id="KETTLE",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Kettle",
                description="A kettle on a table.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        manager._vn_player_message_id = "input-with-general-denial"
        await reconcile_items(
            manager,
            TEXT,
            completed=True,
            resolution="The action was rejected.",
            blocked=True,
            blocked_reason="A general rule rejected this action.",
        )
        response = ChatMessage(session_id=state.session_id, role="assistant", content=TEXT)
        db.add(response)
        await db.flush()
        finish_scene(manager, response)
        finish_conditions(manager, response)
        assert not read(manager.state.entity_states).records
        assert not read_conditions(manager.state.entity_states).conditions


async def test_bad_item_schema_preserves_independent_shared_sections(monkeypatch):
    class MalformedRoles(IndependentRoles):
        denied = False
        actions = [{"item_id": "COAT", "source_owner": "LINA", "destination_owner": "__player__"}]

    async with TestSessionLocal() as db:
        roles, user, avatar, state = await seed(monkeypatch, db, roles=MalformedRoles())
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
        db.add(
            WorldEntity(
                id="KETTLE",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Kettle",
                description="A kettle on a table.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        db.add(
            WorldEntity(
                id="MIKI",
                session_id=state.session_id,
                entity_type="NPC",
                name="Miki",
                description="An adult archivist.",
                current_scene_id="START",
                inventory=[],
                is_hidden=False,
            )
        )
        await db.commit()
        before = list(avatar.inventory)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        assert avatar.inventory == before
        assert any(row.subject_id == "KETTLE" for row in read(state.entity_states).records.values())
        assert any(
            row.target_id == "MIKI"
            for row in read_conditions(state.entity_states).conditions.values()
        )
        assert state.entity_states["__narrated_items__"]["rejected"]
        assert len(roles.calls) == 3


async def test_valid_action_retains_its_original_index_after_a_bad_action(monkeypatch):
    sentence = "Hero picks up a pencil and places it on the desk."

    class MixedRoles(IndependentRoles):
        denied = False
        actions = [
            {"item_id": "COAT", "source_owner": "LINA", "destination_owner": "__player__"},
            {
                "new_item": {
                    "name": "Pencil",
                    "description": "A plain wooden pencil.",
                    "kind": "ordinary",
                },
                "source_owner": "__scene__",
                "destination_owner": "__player__",
                "disposition": "carried",
                "evidence": sentence,
                "basis": "completed",
            },
        ]
        staging = {
            "changes": [],
            "explicit": [],
            "props": [
                {
                    "item_action_index": 1,
                    "owner_id": "__player__",
                    "status": "confirmed",
                    "spatial_position": "on the desk",
                    "evidence": sentence,
                }
            ],
        }

    async with TestSessionLocal() as db:
        _roles, user, avatar, state = await seed(monkeypatch, db, roles=MixedRoles())
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT + " " + sentence)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        pencil = next(item for item in avatar.inventory if item["name"] == "Pencil")
        ledger = state.entity_states["__narrated_items__"]
        assert ledger["accepted"][0]["action_index"] == 1
        assert (
            pencil["id"]
            == "item_" + uuid5(NAMESPACE_URL, f"{state.session_id}:{ledger['message_id']}:1").hex
        )
        assert ledger["rejected_details"][0]["action_index"] == 0
        assert state.entity_states[props.KEY]["items"][0]["item_id"] == pencil["id"]
