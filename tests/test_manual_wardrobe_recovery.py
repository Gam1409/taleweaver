"""Explicit history-backed recovery remains possible when inference proposes nothing."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.clothing.recovery_context import KEY
from backend.engine.debug_engine import DebugEngine
from backend.engine.npc_cards.current_state import character_current_state
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_body_recovery import TEXT


async def prepare(db, monkeypatch, role="assistant", text=TEXT):
    def unavailable(*args, **kwargs):
        raise AssertionError("Manual recovery must not call inference.")

    monkeypatch.setattr("backend.engine.clothing.recovery.GameMasterLLM.for_role", unavailable)
    user, avatar, state, _ = await seed_vn(db)
    state.is_debug_enabled = True
    state.entity_states = {
        **state.entity_states,
        "__manifest_snapshot__": {"original_manifest": {"clothing_settings": {"detailed": True}}},
    }
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.age_years = 32
    npc.visual_profile = {
        "appearance": {"age_years": 32},
        "worn": [],
        "body": {"form": "humanoid", "attachment_slots": ["vaginal", "anal"]},
    }
    message = ChatMessage(session_id=state.session_id, role=role, content=text, scene_id="START")
    db.add(message)
    await db.commit()
    result = await DebugEngine.handle_debug_command(
        db, state, "wardrobe_sources LINA", user=user, avatar=avatar
    )
    assert "sources ready" in result, result
    return user, avatar, state, npc, message


def draft(source):
    return {
        "source_message_id": source,
        "evidence": TEXT,
        "disposition": "worn",
        "attachment_slot": "vaginal",
        "new_item": {"kind": "ordinary", "name": "Пробирка", "description": "Пробирка."},
    }


async def add(db, state, user, avatar, raw):
    return await DebugEngine.handle_debug_command(
        db,
        state,
        "wardrobe_add " + state.entity_states[KEY]["token"] + " " + json.dumps(raw),
        user=user,
        avatar=avatar,
    )


@pytest.mark.parametrize("role", ["assistant", "user"])
async def test_sources_and_manual_draft_need_no_model_and_apply_only_after_selection(
    monkeypatch, role
):
    async with TestSessionLocal() as db:
        user, avatar, state, npc, message = await prepare(db, monkeypatch, role)
        before = deepcopy(state.entity_states)
        minute, inventory = state.in_game_time, deepcopy(avatar.inventory)
        preview = state.entity_states[KEY]
        assert preview["model_step_started"] is False
        assert preview["rejected_sources"][message.id] == TEXT
        result = await add(db, state, user, avatar, draft(message.id))
        assert "proposal added" in result, result
        changed = state.entity_states[KEY]
        assert changed["token"] != preview["token"]
        assert changed["manual_indices"] == [0]
        assert "LINA" not in state.entity_states
        assert state.in_game_time == minute and avatar.inventory == inventory
        assert {key: value for key, value in state.entity_states.items() if key != KEY} == {
            key: value for key, value in before.items() if key != KEY
        }
        accepted = changed["accepted"][0]
        assert accepted["item"]["description"] == "Пробирка."
        assert accepted["attachment_slot"] == "vaginal"
        assert accepted.get("source_role", "assistant") == role
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + changed["token"], user=user, avatar=avatar
        )
        assert "explicit selection" in result and "LINA" not in state.entity_states
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + changed["token"] + " 0", user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
        await db.commit()
        current = await character_current_state(db, state, npc)
        placed = [
            row for row in current["clothing"]["items"] if "BodyVaginal" in row.get("slots", [])
        ]
        assert len(placed) == 1 and placed[0]["item_id"] == accepted["item"]["id"]


async def test_missing_removed_garment_can_use_a_short_description_and_explicit_metadata(
    monkeypatch,
):
    text = "Lina removes her red briefs and puts them on the bed."
    async with TestSessionLocal() as db:
        user, avatar, state, _, message = await prepare(db, monkeypatch, text=text)
        raw = {
            "source_message_id": message.id,
            "evidence": text,
            "disposition": "carried",
            "new_item": {
                "kind": "clothing",
                "name": "Red briefs",
                "description": "Red briefs.",
                "clothing": {"layer": 0, "coverage": ["pelvis"], "underwear": True},
                "wearable_slots": ["Legs"],
            },
        }
        result = await add(db, state, user, avatar, raw)
        assert "proposal added" in result, result
        assert state.entity_states[KEY]["accepted"][0]["disposition"] == "carried"
        assert "LINA" not in state.entity_states


@pytest.mark.parametrize(
    "fault",
    ["disabled", "stale", "quote", "source", "foreign_source", "age", "body", "owner", "duplicate"],
)
async def test_invalid_manual_draft_keeps_the_previous_preview_and_inventory(monkeypatch, fault):
    async with TestSessionLocal() as db:
        user, avatar, state, npc, message = await prepare(db, monkeypatch)
        raw = draft(message.id)
        if fault == "disabled":
            state.is_debug_enabled = False
        if fault == "stale":
            state.entity_states = {**state.entity_states, "unrelated": True}
        if fault == "quote":
            raw["evidence"] = "A different event."
        if fault == "source":
            raw["source_message_id"] = "missing-source"
        if fault == "foreign_source":
            db.add(
                ChatMessage(
                    id="foreign-source", session_id="other-session", role="assistant", content=TEXT
                )
            )
            await db.commit()
            raw["source_message_id"] = "foreign-source"
        if fault == "owner":
            raw["destination_owner"] = "ABSENT"
        if fault in {"age", "body", "duplicate"}:
            if fault == "age":
                npc.age_years = None
                npc.visual_profile = {**npc.visual_profile, "appearance": {}}
            elif fault == "body":
                npc.visual_profile = {
                    **npc.visual_profile,
                    "body": {"form": "humanoid", "attachment_slots": []},
                }
            else:
                npc.inventory = [*npc.inventory, {"id": "TUBE", "name": "Пробирка"}]
            await db.commit()
            await DebugEngine.handle_debug_command(
                db, state, "wardrobe_sources LINA", user=user, avatar=avatar
            )
        before = deepcopy(state.entity_states)
        inventory = deepcopy(avatar.inventory)
        result = await add(db, state, user, avatar, raw)
        assert "DEBUG ERROR" in result, result
        assert state.entity_states == before and avatar.inventory == inventory


async def test_manual_sources_preserve_a_current_preview_and_capacity_rejects_the_next_draft(
    monkeypatch,
):
    text = (
        "Lina retains "
        + ", ".join(f"tube {index}" for index in range(17))
        + " at the documented placement."
    )
    async with TestSessionLocal() as db:
        user, avatar, state, _, message = await prepare(db, monkeypatch, text=text)
        for index in range(16):
            raw = draft(message.id)
            raw["evidence"] = text
            raw["new_item"]["name"] = f"Tube {index}"
            assert "proposal added" in await add(db, state, user, avatar, raw)
        before = deepcopy(state.entity_states)
        await DebugEngine.handle_debug_command(
            db, state, "wardrobe_sources LINA", user=user, avatar=avatar
        )
        assert state.entity_states == before
        raw["new_item"]["name"] = "Tube 16"
        result = await add(db, state, user, avatar, raw)
        assert "DEBUG ERROR" in result
        assert state.entity_states == before
