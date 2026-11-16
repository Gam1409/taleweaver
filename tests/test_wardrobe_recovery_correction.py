"""A rejected model proposal can be explicitly corrected without inventing evidence."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import entry

TEXT = "Лина носит синий халат и красные шёлковые стринги. Стринги спущены до колен."
CORRECTION = {
    "status": "worn",
    "evidence": "красные шёлковые стринги",
    "uncovered_regions": ["pelvis"],
    "placement_evidence": "Стринги спущены до колен.",
}


async def preview(db, monkeypatch):
    from backend.engine.clothing import recovery

    user, avatar, state, _ = await seed_vn(db)
    state.is_debug_enabled = True
    state.entity_states = {
        **state.entity_states,
        "__manifest_snapshot__": {"original_manifest": {"clothing_settings": {"detailed": True}}},
    }
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.age_years = 32
    message = ChatMessage(
        session_id=state.session_id, role="assistant", content=TEXT, scene_id="START"
    )
    db.add(message)
    await db.commit()
    coat = entry(message.id)
    coat.action.evidence = TEXT
    garment = entry(message.id, name="Красные шёлковые стринги")
    garment.action.new_item.clothing.coverage = ["pelvis"]
    garment.action.new_item.clothing.layer = 0
    garment.action.new_item.clothing.underwear = True
    garment.action.new_item.wearable_slots = ["Legs"]
    garment.action.disposition = "carried"
    garment.action.evidence = "Красное... Стринги."
    garment.uncovered_regions = ["pelvis"]
    garment.placement_evidence = "спущены... до колен"
    proposal = RecoveryProposal(entries=[coat, garment])
    llm = SimpleNamespace(model="test", aexecute_complex_task=AsyncMock(return_value=proposal))
    monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
    result = await DebugEngine.handle_debug_command(
        db, state, "wardrobe_preview LINA", user=user, avatar=avatar
    )
    assert "preview ready" in result, result
    assert llm.aexecute_complex_task.await_count == 2
    assert len(state.entity_states[KEY]["accepted"]) == 1
    assert state.entity_states[KEY]["rejected_entries"][0]["index"] == 1
    return user, avatar, state, npc, llm


def command(token, correction=None, index=1):
    payload = json.dumps(CORRECTION if correction is None else correction, ensure_ascii=False)
    return f"wardrobe_correct {token} {index} {payload}"


@pytest.mark.asyncio
async def test_correct_partial_wear_then_apply_only_that_garment(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state, npc, llm = await preview(db, monkeypatch)
        original = deepcopy(state.entity_states)
        template_inventory = deepcopy(npc.inventory)
        player_inventory = deepcopy(avatar.inventory)
        token = original[KEY]["token"]
        result = await DebugEngine.handle_debug_command(
            db, state, command(token), user=user, avatar=avatar
        )
        assert "corrected" in result, result
        corrected = state.entity_states[KEY]
        assert corrected["token"] != token and not corrected["errors"]
        assert corrected["accepted"][0] == original[KEY]["accepted"][0]
        assert "LINA" not in state.entity_states
        assert avatar.inventory == player_inventory and npc.inventory == template_inventory
        corrected_item = corrected["accepted"][1]
        assert corrected_item["disposition"] == "worn"
        assert corrected_item["uncovered_regions"] == ["pelvis"]
        assert corrected_item["evidence"] == CORRECTION["evidence"]
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + corrected["token"] + " 1", user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
        await db.commit()
        await db.refresh(state)
        actor = state.entity_states["LINA"]
        assert actor["inventory"] == [*template_inventory, corrected_item["item"]]
        assert actor["visual_profile"]["worn"] == [
            {
                "item_id": corrected_item["item"]["id"],
                "uncovered_regions": ["pelvis"],
                "source": {
                    "request_id": None,
                    "source_message_id": corrected_item["source_message_id"],
                    "content_hash": sha256(TEXT.encode()).hexdigest(),
                    "evidence": CORRECTION["placement_evidence"],
                },
            }
        ]
        assert avatar.inventory == player_inventory and npc.inventory == template_inventory
        assert llm.aexecute_complex_task.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["quote", "carried", "coverage", "owner", "stale", "disabled"])
async def test_invalid_correction_preserves_preview_and_possessions(monkeypatch, failure):
    async with TestSessionLocal() as db:
        user, avatar, state, _, llm = await preview(db, monkeypatch)
        correction = deepcopy(CORRECTION)
        token = state.entity_states[KEY]["token"]
        if failure == "quote":
            correction["evidence"] = "Invented garment quote."
        if failure == "carried":
            correction["status"] = "carried"
        if failure == "coverage":
            correction["uncovered_regions"] = ["feet"]
        if failure == "owner":
            correction["destination_owner"] = "__player__"
        if failure == "stale":
            state.entity_states = {**state.entity_states, "changed": True}
        if failure == "disabled":
            state.is_debug_enabled = False
        before = deepcopy(state.entity_states)
        inventory = deepcopy(avatar.inventory)
        result = await DebugEngine.handle_debug_command(
            db, state, command(token, correction), user=user, avatar=avatar
        )
        assert "DEBUG ERROR" in result, result
        assert state.entity_states == before and avatar.inventory == inventory
        assert llm.aexecute_complex_task.await_count == 2


@pytest.mark.asyncio
async def test_copied_quotes_with_edge_whitespace_still_apply_after_preview_revalidation(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        user, avatar, state, _, _ = await preview(db, monkeypatch)
        correction = deepcopy(CORRECTION)
        correction["evidence"] = "\n  " + correction["evidence"] + " \n"
        correction["placement_evidence"] = "\t" + correction["placement_evidence"] + "\n"
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            command(state.entity_states[KEY]["token"], correction),
            user=user,
            avatar=avatar,
        )
        assert "corrected" in result, result
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            "wardrobe_apply " + state.entity_states[KEY]["token"] + " 1",
            user=user,
            avatar=avatar,
        )
        assert "Recovered 1" in result, result
