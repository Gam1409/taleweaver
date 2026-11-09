"""Reuse staging state while extracting item and spatial deltas in one request."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_staging import props
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

TEXT = "Lina takes off her blue coat and puts it on the bench. Lina sits beside Hero."
COAT = {
    "id": "COAT",
    "name": "Blue coat",
    "description": "A blue wool coat.",
    "clothing": {"layer": 2, "coverage": ["torso", "arms"], "opaque": True},
    "wearable_slots": ["Chest"],
}
ACTION = {
    "item_id": "COAT",
    "source_owner": "LINA",
    "destination_owner": "LINA",
    "disposition": "carried",
    "basis": "completed",
    "evidence": TEXT.split(" Lina sits", maxsplit=1)[0],
}
STAGING = {
    "changes": [
        {
            "entity_id": "LINA",
            "posture": "sitting",
            "evidence": "Lina sits beside Hero.",
            "placement": {"relation": "beside", "target_kind": "character", "target": PLAYER},
        }
    ],
    "props": [
        {
            "item_id": "COAT",
            "owner_id": "LINA",
            "status": "confirmed",
            "spatial_position": "on the bench",
            "evidence": ACTION["evidence"],
        }
    ],
}


class SharedRoles(TurnRoles):
    actions = [ACTION]
    staging = STAGING
    fail = False

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema in (ItemExtraction, SharedItemExtraction):
            self.calls.append((schema.__name__, args, kwargs))
            if self.fail:
                raise TimeoutError("Unavailable shared extractor")
            router = object.__new__(GameMasterLLM)
            response = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "actions": self.actions,
                                    **(
                                        {"staging": self.staging}
                                        if schema is SharedItemExtraction
                                        else {}
                                    ),
                                }
                            )
                        ),
                        finish_reason="stop",
                    )
                ]
            )
            return router._parse_structured_content(response, schema)
        if schema is SceneExtraction:
            self.calls.append((schema.__name__, args, kwargs))
            raise AssertionError("A turn must not send a second staging request")
        return await super().structured(*args, **kwargs)


async def seed(monkeypatch, db, *, enabled=True, roles=None):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
    roles = roles or SharedRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("backend.engine.scene_staging.runtime.GameMasterLLM", roles)
    user, avatar, state, _ = await seed_vn(db)
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.inventory = [COAT]
    npc.visual_profile = {"appearance": {"age_years": 25}, "worn": [{"item_id": "COAT"}]}
    write_settings(state, VnSettings(scene_staging=enabled))
    await db.commit()
    return roles, user, avatar, state


async def test_one_shared_request_keeps_removal_placement_and_pose(monkeypatch):
    async with TestSessionLocal() as db:
        roles, user, avatar, state = await seed(monkeypatch, db)
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert len(roles.calls) == 3
        assert not any(call[0] == "SceneExtraction" for call in roles.calls)
        await db.refresh(state)
        reply = await db.scalar(select(ChatMessage).where(ChatMessage.content == TEXT))
        facts = registry_of(state.entity_states)["snapshots"][reply.id]["visible_facts"]
        lina = next(row for row in facts["characters"] if row["id"] == "LINA")
        assert facts["staging_status"] == "ready"
        assert lina["posture"] == "sitting" and lina["placement"]["target"] == avatar.id
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        assert any(
            row["item_id"] == "COAT" and row["spatial_position"] == "on the bench"
            for row in facts["props"]
        )
        assert state.entity_states[KEY]["source_message_id"] == reply.id
        assert state.entity_states[props.KEY]["items"][0]["source_message_id"] == reply.id


async def test_placed_item_and_pose_survive_forty_dialogue_turns(monkeypatch):
    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db)
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        original = deepcopy(registry_of(state.entity_states)["snapshots"])
        state.max_memory_turns = 10
        await db.commit()
        roles.actions, roles.staging = [], {"changes": [], "props": []}
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", 'Lina says, "All right."')
        for _ in range(40):
            events = [
                chunk
                async for chunk in GameTurnManager(db, state.session_id, user).process_turn(
                    "Tell me more."
                )
            ]
            assert final_payload(events)["status"] == "success", "".join(events)
        assert "on the bench" in str(roles.prompts[-1])
        assert "Blue coat" in str(roles.prompts[-1])
        assert "sitting" in str(roles.prompts[-1])
        assert TEXT not in str(roles.prompts[-1])
        assert len(roles.calls) == 123
        await db.refresh(state)
        current = registry_of(state.entity_states)["snapshots"]
        assert all(current[identifier] == snapshot for identifier, snapshot in original.items())


@pytest.mark.parametrize(
    "staging",
    [
        None,
        "malformed",
        {
            "changes": [
                {"entity_id": "ABSENT", "posture": "sitting", "evidence": "Lina sits beside Hero."}
            ]
        },
    ],
)
async def test_bad_or_missing_staging_does_not_veto_valid_item_changes(monkeypatch, staging):
    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db)
        roles.staging = staging
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert len(roles.calls) == 3 and state.entity_states[KEY]["status"] == "unconfirmed"
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []


@pytest.mark.parametrize("invalid", ["quote", "schema"])
async def test_rejected_item_change_does_not_veto_valid_pose_or_allow_worn_prop(
    monkeypatch, invalid
):
    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db)
        roles.actions = (
            [{**ACTION, "evidence": "An invented removal."}] if invalid == "quote" else "malformed"
        )
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert len(roles.calls) == 3
        assert state.entity_states[KEY]["actors"]["LINA"]["posture"]["value"] == "sitting"
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        assert (state.entity_states.get("LINA") or {}).get("visual_profile", npc.visual_profile)[
            "worn"
        ] == [{"item_id": "COAT", "uncovered_regions": []}]
        assert not props.project(state, [{"item_id": "COAT", "owner_id": "LINA"}])
        assert state.entity_states[KEY]["rejected_props"] == 1


async def test_disabled_setting_keeps_original_schema_and_item_request(monkeypatch):
    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db, enabled=False)
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert len(roles.calls) == 3 and KEY not in state.entity_states
        assert props.KEY not in state.entity_states
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        assert "staging" not in ItemExtraction.model_json_schema()["properties"]


async def test_shared_timeout_does_not_send_a_fallback_staging_request(monkeypatch):
    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db)
        roles.fail = True
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert len(roles.calls) == 3 and state.entity_states[KEY]["status"] == "unconfirmed"
        assert not any(call[0] == "SceneExtraction" for call in roles.calls)


async def test_host_rejection_keeps_independent_pose_without_applying_item_changes(monkeypatch):
    class BlockedRoles(SharedRoles):
        async def structured(self, *args, **kwargs):
            result = await super().structured(*args, **kwargs)
            if type(result).__name__.startswith("VNProgressionIntent"):
                result.removed_inventory_item_ids = ["NOT_OWNED"]
            return result

    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db, roles=BlockedRoles())
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert len(roles.calls) == 3 and state.entity_states[KEY]["status"] == "ready"
        assert state.entity_states["__narrated_items__"]["reason_code"] == "rules_rejected"
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        assert (state.entity_states.get("LINA") or {}).get("visual_profile", npc.visual_profile)[
            "worn"
        ] == [{"item_id": "COAT", "uncovered_regions": []}]


async def test_new_prop_reference_uses_original_action_index_after_a_rejected_action(monkeypatch):
    text = "Hero picks up a plain paper note and puts it on the desk."
    async with TestSessionLocal() as db:
        roles, user, avatar, state = await seed(monkeypatch, db)
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
        roles.actions = [
            {**ACTION, "evidence": "An invented removal."},
            {
                "new_item": {
                    "name": "Paper note",
                    "description": "An ordinary paper note.",
                    "kind": "ordinary",
                },
                "source_owner": "__scene__",
                "destination_owner": PLAYER,
                "disposition": "carried",
                "basis": "completed",
                "evidence": text,
            },
        ]
        roles.staging = {
            "props": [
                {
                    "item_action_index": 1,
                    "owner_id": PLAYER,
                    "status": "confirmed",
                    "spatial_position": "on the desk",
                    "evidence": text,
                }
            ]
        }
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        entries = state.entity_states[props.KEY]["items"]
        assert len(entries) == 1 and entries[0]["owner_id"] == avatar.id
        assert entries[0]["item_id"] == avatar.inventory[0]["id"]
        assert entries[0]["spatial_position"] == "on the desk" and len(roles.calls) == 3
