"""Successful drops clear only the transferred aliases; rejected drops remain observable."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.system_diagnostics import service
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.inventory_transfer_support import seed_manager
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)

pytestmark = pytest.mark.asyncio
RING = {
    "id": "RING",
    "name": "Plain ring",
    "description": "A plain archive ring.",
    "item_type": "WEARABLE",
    "wearable_slots": ["Ring_1"],
    "clothing": {"layer": 2, "coverage": ["hands"], "category": "accessory"},
    "stat_modifier_dexterity": 3,
}
OTHER = {**RING, "id": "OTHER", "name": "Other ring"}


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def held_row(manager):
    return WorldEntity(
        id="RING",
        session_id=manager.game_id,
        entity_type="OBJECT",
        item_type="WEARABLE",
        name=RING["name"],
        description=RING["description"],
        current_scene_id="INVENTORY",
        is_in_inventory=True,
        metadata_json=deepcopy(RING),
    )


@pytest.mark.parametrize("world_row", [False, True])
async def test_drop_clears_only_dropped_equipment_and_worn_aliases_after_reload(world_row):
    service.set_enabled(False)
    profile = {
        "appearance": {"age_years": 30},
        "worn": [{"item_id": "RING"}, {"item_id": "OTHER"}],
        "extension_data": {"keep": True},
    }
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, mode="vn", inventory=[RING, OTHER])
        manager.avatar.equipment = {
            "ring_1": deepcopy(RING),
            "Ring_2": deepcopy(OTHER),
            "MainHand": "RING",
        }
        manager.avatar.visual_profile = deepcopy(profile)
        if world_row:
            db.add(held_row(manager))
        await db.commit()
        chunks = [chunk async for chunk in manager.process_turn("/drop Plain ring")]
        assert "You dropped Plain ring." in "".join(chunks)
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "transfer-avatar")
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "transfer-session")
        )
        assert avatar.inventory == [OTHER]
        assert avatar.equipment["ring_1"] is None
        assert avatar.equipment["MainHand"] is None
        assert avatar.equipment["Ring_2"] == OTHER
        assert avatar.visual_profile == {**profile, "worn": [{"item_id": "OTHER"}]}
        rows = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        snapshot = possession_snapshot(
            type("SavedView", (), {"avatar": avatar, "state": state})(), rows
        )
        assert snapshot.owners["RING"] == SCENE


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("failure", ["identity", "destination"])
async def test_failed_drop_preserves_all_possessions_and_respects_trace_toggle(
    monkeypatch, enabled, failure
):
    item = deepcopy(RING)
    if failure == "identity":
        item.pop("id")
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, mode="vn", inventory=[item])
        manager.avatar.equipment = {"Ring_1": deepcopy(item)}
        profile = {"worn": [{"item_id": "RING"}]}
        manager.avatar.visual_profile = deepcopy(profile)
        if failure == "destination":
            db.add(held_row(manager))
        await db.commit()
        service.set_enabled(True, state_failure_traces=enabled)
        monkeypatch.setattr(manager, "_spawn_scene_item", AsyncMock(return_value=None))
        chunks = [chunk async for chunk in manager.process_turn("/drop Plain ring")]
        assert "You dropped" not in "".join(chunks)
        assert manager.avatar.inventory == [item]
        assert manager.avatar.equipment["Ring_1"] == item
        assert manager.avatar.visual_profile == profile
        assert len(trace_files()) == int(enabled)
        if enabled:
            reasons = event_payloads(trace_rows(), "state.rejected")
            rejection = next(reason for reason in reasons if reason["domain"] == "inventory")
            assert rejection["reason_code"] == f"inventory.drop_{failure}_invalid"
            details = rejection["details"]
            assert details["proposal"] == item
            assert details["expected"]["current_scene_id"] == "START"
            assert details["source"]["owner"] == "__player__"


@pytest.mark.parametrize("enabled", [False, True])
async def test_successful_drop_does_not_create_rejection_trace(enabled):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, mode="vn", inventory=[RING])
        service.set_enabled(True, state_failure_traces=enabled)
        chunks = [chunk async for chunk in manager.process_turn("/drop Plain ring")]
        assert "You dropped Plain ring." in "".join(chunks)
        assert trace_files() == []
