"""Prepass source policy fits the existing VN request and canonical item owners."""

import json
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.movement_intent import confirm_player_movement
from backend.engine.npc_actions import preparation as action_preparation
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.engine.visual_novel.intent import (
    VNEntityUpdate,
    VNProgressionIntent,
    build_progression_context,
    progression_prompt,
)
from backend.models.world_entity import WorldEntity, WorldExit
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_prepass_placements import (
    PLACEMENT,
    REQUEST,
    apply,
    current,
    placement,
    proof,
    setup,
)


@pytest.mark.parametrize("active", [False, True])
async def test_progression_context_prompt_and_optional_schema_describe_only_the_active_policy(
    active,
):
    async with TestSessionLocal() as db:
        manager, _, _ = await setup(db, settings={"action_tools": active})
        context = build_progression_context(
            manager,
            npcs=[],
            scenes=[{"id": "START"}],
            exits=[],
            entities=await session_objects(db, manager.game_id),
        )
        payload = json.loads(context.split("\n", 1)[1])
        assert ("npc_command_control" in payload) == active
        assert ("NPC COMMAND PLACEMENT" in progression_prompt(manager.state)) == active
        source = VNEntityUpdate.model_json_schema()["properties"]["movement_source"]
        assert "portable OBJECT placements" in source["description"]
        assert VNEntityUpdate(entity_id="BRASS_KEY").movement_source is None


async def test_deferred_spatial_field_does_not_reject_an_existing_player_transfer():
    async with TestSessionLocal() as db:
        manager, _, _ = await setup(db)
        raw = placement()
        raw["new_inventory_items"] = [{"id": "BRASS_KEY", "name": "Brass key"}]
        _, notices = await apply(manager, raw)
        snapshot = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert snapshot.owners["BRASS_KEY"] == "__player__" and notices
        assert any(item["id"] == "BRASS_KEY" for item in manager.avatar.inventory)
        assert manager.state.entity_states["BRASS_KEY"]["notes"] == "Retain this independent note."


@pytest.mark.parametrize("gate", ["unconfirmed", "confirmed", "missing_route"])
async def test_portable_map_placement_uses_the_existing_player_traversal_owner(monkeypatch, gate):
    text = "I roll the key into the annex and follow it through the door."
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text=text)
        if gate != "missing_route":
            db.add(
                WorldExit(
                    session_id=manager.game_id,
                    from_scene_id="START",
                    to_scene_id="ANNEX",
                    label="Door",
                    exit_type="one_way",
                    is_locked=False,
                )
            )
            await db.commit()
        raw = placement(source=proof(), field="moved_entities")
        raw["moved_entities"][0]["to_spatial_position"] = "on the annex floor"
        if gate != "unconfirmed":
            proposal = VNProgressionIntent.model_validate({**raw, "new_scene_id": "ANNEX"})
            classifier = AsyncMock(
                return_value={
                    "explicit_transition": True,
                    "destination_id": "ANNEX",
                    "action_quote": request.content,
                }
            )
            monkeypatch.setattr(manager.adventure_gen, "classify_short_intent", classifier)
            await confirm_player_movement(
                manager,
                proposal,
                user_msg=request.content,
                scenes=[{"id": "START"}, {"id": "ANNEX"}],
                exits=[{"to_scene_id": "ANNEX", "is_locked": False}],
                entities=await session_objects(db, manager.game_id),
                history=[],
            )
            raw = proposal.model_dump()
        _, notices = await apply(manager, raw)
        confirmed = gate == "confirmed"
        assert bool(notices) != confirmed
        assert current(manager, key, "current_scene_id") == ("ANNEX" if confirmed else "START")
        assert current(manager, key) == ("on the annex floor" if confirmed else "on the table")
        assert manager.state.current_scene_id == ("ANNEX" if confirmed else "START")


async def test_valid_player_local_movement_uses_the_same_optional_source():
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, text=PLACEMENT)
        raw = placement(source=proof(), field="moved_entities")
        raw["moved_entities"][0].update(to_scene_id=None, to_spatial_position="on the bench")
        _, notices = await apply(manager, raw)
        assert current(manager, key) == "on the bench" and not notices


class PrepassActionRoles(ActionRoles):
    @staticmethod
    def commands():
        return [
            {"name": "take_item", "arguments": {"item_id": "BRASS_KEY"}},
            {
                "name": "give_item",
                "arguments": {"item_id": "BRASS_KEY", "recipient_id": "@player"},
            },
        ]

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.updated_entities = [
                VNEntityUpdate(entity_id="BRASS_KEY", spatial_position="in Lina's hand")
            ]
        return result


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_unproven_prepass_does_not_replace_the_live_command_source_view(
    monkeypatch, protocol
):
    roles = PrepassActionRoles()
    install(monkeypatch, roles)
    observed_positions = []
    original_capture = action_preparation.capture

    async def capture_source(manager, views, observation):
        observed_positions.append(views["LINA"].entities["BRASS_KEY"]["spatial_position"])
        return await original_capture(manager, views, observation)

    monkeypatch.setattr(action_preparation, "capture", capture_source)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        db.add(
            WorldEntity(
                id="BRASS_KEY",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Brass key",
                description="An ordinary brass key.",
                current_scene_id="START",
                spatial_position="on the table",
                is_portable=True,
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        manager, chunks = await run(db, user, REQUEST)
        assert any(row.startswith("event: final") for row in chunks), "".join(chunks)
        assert not any(row.startswith("event: error") for row in chunks), "".join(chunks)
        assert observed_positions == ["on the table"]
        assert roles.reconciliations[-1]["owners"]["BRASS_KEY"] == "__player__"
        assert load(manager.state).usage.calls == 4
