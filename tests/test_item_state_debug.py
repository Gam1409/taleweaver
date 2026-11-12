"""Manual item corrections use existing canonical possession sources."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.command_parser import CommandParser
from backend.engine.physical_conditions.debug import command, view
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

COAT = {"id": "COAT", "name": "Travel coat", "item_type": "WEARABLE", "slot": "Chest"}


async def correction(db, state, avatar, **fields):
    fields.setdefault("expected_revision", read(state.entity_states).revision)
    return await command(db, state, "condition " + json.dumps(fields), avatar=avatar)


async def equipped_world(db):
    _, avatar, state, _ = await seed_vn(db)
    state.is_debug_enabled = True
    state.in_game_time = 120
    avatar.inventory = [deepcopy(COAT)]
    avatar.equipment = {}
    response = CommandParser._handle_equip(avatar, COAT["name"])
    assert "Equipped" in response
    assert not avatar.inventory and avatar.equipment["Chest"] == COAT
    assert (
        possession_snapshot(SimpleNamespace(state=state, avatar=avatar), []).owners["COAT"]
        == "__player__"
    )
    await db.commit()
    return avatar, state


@pytest.mark.asyncio
@pytest.mark.parametrize("load_avatar", [False, True])
async def test_equipped_inline_item_can_be_recorded_and_corrected_without_world_row(load_avatar):
    async with TestSessionLocal() as db:
        avatar, state = await equipped_world(db)
        possessions = deepcopy((avatar.inventory, avatar.equipment))
        response = await correction(
            db,
            state,
            None if load_avatar else avatar,
            operation="record",
            target_id="COAT",
            kind="item_state",
            part="form",
            detail="The coat is smooth.",
            visibility="private",
        )
        assert response.startswith("DEBUG: Updated"), response
        original = next(iter(read(state.entity_states).conditions.values()))
        response = await correction(
            db,
            state,
            None if load_avatar else avatar,
            operation="change",
            condition_id=original.id,
            detail="The coat is crumpled.",
            visibility="private",
        )
        assert response.startswith("DEBUG: Updated"), response
        current = read(state.entity_states).conditions[original.id]
        assert current.target_id == "COAT" and current.detail == "The coat is crumpled."
        assert current.latest.kind == "manual" and current.status == "active"
        assert current.first_recorded_minute == current.last_changed_minute == 120
        assert current.id == original.id
        assert (avatar.inventory, avatar.equipment) == possessions and state.in_game_time == 120


@pytest.mark.asyncio
async def test_debug_subjects_include_equipped_item_with_canonical_labels_preferred():
    async with TestSessionLocal() as db:
        avatar, state = await equipped_world(db)
        subjects = view(state, [], [], avatar)["subjects"]
        assert {"id": "COAT", "name": "Travel coat"} in subjects
        canonical = view(state, [], [{"id": "COAT", "name": "Current coat name"}], avatar)
        assert [row for row in canonical["subjects"] if row["id"] == "COAT"] == [
            {"id": "COAT", "name": "Current coat name"}
        ]


@pytest.mark.asyncio
async def test_string_only_equipment_does_not_establish_item_ownership():
    async with TestSessionLocal() as db:
        avatar, state = await equipped_world(db)
        avatar.equipment = {"Chest": "MISSING_COAT"}
        previous = deepcopy(state.entity_states)
        response = await correction(
            db,
            state,
            avatar,
            operation="record",
            target_id="MISSING_COAT",
            kind="item_state",
            part="form",
            detail="The coat is smooth.",
        )
        assert response.startswith("DEBUG ERROR:"), response
        assert state.entity_states == previous
        assert all(row["id"] != "MISSING_COAT" for row in view(state, [], [], avatar)["subjects"])


@pytest.mark.asyncio
async def test_equipped_item_keeps_revision_and_debug_guards_and_body_corrections():
    async with TestSessionLocal() as db:
        avatar, state = await equipped_world(db)
        state.is_debug_enabled = False
        response = await correction(
            db,
            state,
            avatar,
            operation="record",
            target_id="COAT",
            kind="item_state",
            part="form",
            detail="The coat is smooth.",
        )
        assert "Enable debug mode first" in response
        state.is_debug_enabled = True
        response = await correction(
            db,
            state,
            avatar,
            operation="record",
            target_id="__player__",
            kind="injury",
            part="arm",
            detail="A small scratch.",
        )
        assert response.startswith("DEBUG: Updated"), response
        body_id = next(iter(read(state.entity_states).conditions))
        before = deepcopy(state.entity_states)
        response = await correction(
            db,
            state,
            avatar,
            operation="record",
            target_id="COAT",
            kind="item_state",
            part="form",
            detail="The coat is smooth.",
            expected_revision=0,
        )
        assert "Refresh before editing" in response and state.entity_states == before
        response = await correction(db, state, avatar, operation="heal", condition_id=body_id)
        assert response.startswith("DEBUG: Updated"), response
        assert read(state.entity_states).conditions[body_id].status == "resolved"


@pytest.mark.parametrize("source", ["inventory", "override", "metadata"])
@pytest.mark.asyncio
async def test_npc_worn_items_keep_existing_authoritative_inventory_paths(source):
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "LINA"
            )
        )
        npc.inventory = [deepcopy(COAT)] if source == "inventory" else []
        if source == "metadata":
            npc.metadata_json = {"inventory": [deepcopy(COAT)]}
        override = {
            "visual_profile": {"appearance": {"age_years": 30}, "worn": [{"item_id": "COAT"}]}
        }
        if source == "override":
            override["inventory"] = [deepcopy(COAT)]
        state.entity_states = {**state.entity_states, npc.id: override}
        before = deepcopy(state.entity_states[npc.id])
        response = await correction(
            db,
            state,
            avatar,
            operation="record",
            target_id="COAT",
            kind="item_state",
            part="form",
            detail="The coat is smooth.",
        )
        assert response.startswith("DEBUG: Updated"), response
        row = next(iter(read(state.entity_states).conditions.values()))
        response = await correction(
            db,
            state,
            avatar,
            operation="change",
            condition_id=row.id,
            detail="The coat is crumpled.",
        )
        assert response.startswith("DEBUG: Updated"), response
        assert read(state.entity_states).conditions[row.id].detail == "The coat is crumpled."
        assert state.entity_states[npc.id] == before
