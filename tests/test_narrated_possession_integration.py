"""Observed possessions share the existing source, independent-section and replay boundaries."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_staging import props
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

TEXT = 'Lina is holding her plain paper map. Lina says, "I will check it myself."'


class PossessionRoles(TurnRoles):
    item_id = None
    mixed = False

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        payload = json.loads(args[1])
        references = list(payload["completed_narration"])
        observed = {
            "item_id": self.item_id,
            "new_item": None
            if self.item_id
            else {"kind": "ordinary", "name": "Paper map", "description": "A plain paper map."},
            "source_owner": "LINA",
            "destination_owner": "LINA",
            "disposition": "held",
            "basis": "observed_possession",
            "evidence": references[0],
        }
        updates = {}
        actions = [observed]
        if self.mixed:
            actions.insert(
                0,
                {
                    **observed,
                    "item_id": "HIDDEN_RING",
                    "new_item": None,
                    "source_owner": "__player__",
                    "destination_owner": "__player__",
                },
            )
            updates["scene_updates"] = [
                {
                    "operation": "record",
                    "key": "lamp",
                    "kind": "environment",
                    "subject_id": "START",
                    "detail": "The lamp is lit.",
                    "evidence": references[-1],
                    "visibility": "public",
                }
            ]
        if payload.get("scene_staging") is not None:
            updates["staging"] = {"changes": [], "props": [], "explicit": []}
        return extraction(schema, actions=actions, **updates)


@pytest.mark.parametrize("staging", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
async def test_discovery_preserves_transcript_independent_sections_and_future_observation(
    monkeypatch, staging, mixed
):
    roles = PossessionRoles()
    roles.mixed = mixed
    install_roles(monkeypatch, roles)
    text = TEXT + (" The lamp is lit." if mixed else "")
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        write_settings(state, VnSettings(scene_staging=staging))
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        original_player = deepcopy((avatar.inventory, avatar.equipment))
        original_items = deepcopy(npc.inventory)
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I wait quietly."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        inventory = state.entity_states["LINA"]["inventory"]
        assert inventory[:-1] == original_items
        registered = inventory[-1]
        roles.item_id = registered["id"]
        assert (avatar.inventory, avatar.equipment) == original_player
        checked = state.entity_states[KEY]
        assert bool(checked["rejected"]) is mixed
        assert checked["accepted"][0]["action_index"] == (1 if mixed else 0)
        if mixed:
            records = state.entity_states["__scene_continuity__"]["records"].values()
            assert any(row["key"] == "lamp" and row["status"] == "active" for row in records)
        reply = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant", ChatMessage.content == text)
        )
        assert reply is not None and reply.content == text
        assert checked["narration_source"]["message_id"] == reply.id
        assert len(roles.calls) == 3
        # A fresh ownership observation cannot erase an already confirmed location.
        state.entity_states = {
            **state.entity_states,
            props.KEY: {
                "items": [
                    {
                        "item_id": registered["id"],
                        "owner_id": "LINA",
                        "scene_id": "START",
                        "status": "confirmed",
                        "spatial_position": "in her bag",
                        "visibility": "public",
                    }
                ]
            },
        }
        await db.commit()
        placement = deepcopy(state.entity_states[props.KEY])
        roles.mixed = False
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I keep waiting."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert state.entity_states["LINA"]["inventory"] == inventory
        assert not state.entity_states[KEY]["accepted"]
        assert state.entity_states[props.KEY] == placement
        assert len(roles.calls) == 6
        saved_id = state.id
    async with TestSessionLocal() as db:
        restored = await db.get(SessionState, saved_id)
        assert restored.entity_states["LINA"]["inventory"] == inventory


async def test_full_replay_reregisters_once_from_the_existing_input_boundary(monkeypatch):
    roles = PossessionRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I wait quietly.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        before = deepcopy(state.entity_states["LINA"]["inventory"])
        reply = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant", ChatMessage.content == TEXT)
        )
        original_reply_id = reply.id
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "ignored", replay_message_id=reply.id
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        inventory = state.entity_states["LINA"]["inventory"]
        assert inventory[:-1] == before[:-1] and len(inventory) == len(before)
        # Full regeneration replaces its source input and rebuilds runtime identities.
        assert inventory[-1]["id"] != before[-1]["id"]
        assert {
            key: value for key, value in inventory[-1].items() if key not in {"id", "item_origin"}
        } == {key: value for key, value in before[-1].items() if key not in {"id", "item_origin"}}
        origin = inventory[-1]["item_origin"]["source_message_id"]
        assert origin == final_payload(events)["saved_user_message_id"]
        assert await db.get(ChatMessage, original_reply_id) is None
        assert len(roles.calls) == 6
