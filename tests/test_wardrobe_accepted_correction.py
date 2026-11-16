"""Exact quotations can be about the wrong item; reviewed candidates remain correctable."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import TEXT, entry

WRONG = "A red scarf lies on the chair."
RIGHT = "Lina carries her black shoes in her hands."


async def preview(db, monkeypatch, source_role="assistant"):
    user, avatar, state, _ = await seed_vn(db)
    state.is_debug_enabled = True
    messages = [
        ChatMessage(session_id=state.session_id, role=role, content=text, scene_id="START")
        for role, text in [("assistant", TEXT), ("user", WRONG), (source_role, RIGHT)]
    ]
    db.add_all(messages)
    await db.commit()
    coat = entry(messages[0].id)
    shoes = entry(messages[1].id, name="Black shoes")
    shoes.action.new_item.description = "Black leather shoes."
    shoes.action.new_item.clothing.coverage = ["feet"]
    shoes.action.new_item.wearable_slots = ["Feet"]
    shoes.action.disposition = "carried"
    shoes.action.basis = "completed"
    shoes.action.evidence = WRONG
    llm = SimpleNamespace(
        model="test",
        aexecute_complex_task=AsyncMock(return_value=RecoveryProposal(entries=[coat, shoes])),
    )
    monkeypatch.setattr("backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: llm)
    result = await DebugEngine.handle_debug_command(
        db, state, "wardrobe_preview LINA", user=user, avatar=avatar
    )
    assert "preview ready" in result, result
    assert len(state.entity_states[KEY]["accepted"]) == 2
    assert llm.aexecute_complex_task.await_count == 1
    return user, avatar, state, messages, llm


def command(token, source_id, quote=RIGHT, index=1):
    return (
        "wardrobe_correct "
        + token
        + f" {index} "
        + json.dumps({"status": "carried", "source_message_id": source_id, "evidence": quote})
    )


@pytest.mark.parametrize("source_role", ["assistant", "user"])
async def test_accepted_wrong_item_quote_can_be_rebound_before_explicit_application(
    monkeypatch, source_role
):
    async with TestSessionLocal() as db:
        user, avatar, state, messages, llm = await preview(db, monkeypatch, source_role)
        original = deepcopy(state.entity_states)
        inventory = deepcopy(avatar.inventory)
        old = original[KEY]
        result = await DebugEngine.handle_debug_command(
            db, state, command(old["token"], messages[2].id), user=user, avatar=avatar
        )
        assert "corrected" in result, result
        updated = state.entity_states[KEY]
        assert updated["token"] != old["token"]
        assert updated["accepted"][0] == old["accepted"][0]
        shoes = updated["accepted"][1]
        assert shoes["source_message_id"] == messages[2].id and shoes["evidence"] == RIGHT
        assert shoes.get("source_role", "assistant") == source_role
        assert "LINA" not in state.entity_states and avatar.inventory == inventory
        assert updated["rejected_sources"][messages[2].id] == RIGHT
        assert {row["index"] for row in updated["review_entries"]} == {0, 1}
        assert "missing or has been replaced" in await DebugEngine.handle_debug_command(
            db, state, command(old["token"], messages[2].id), user=user, avatar=avatar
        )
        if source_role == "user":
            result = await DebugEngine.handle_debug_command(
                db, state, "wardrobe_apply " + updated["token"], user=user, avatar=avatar
            )
            assert "require explicit selection" in result
            assert "LINA" not in state.entity_states
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + updated["token"] + " 1", user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
        assert shoes["item"] in state.entity_states["LINA"]["inventory"]
        assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.parametrize(
    "fault", ["unknown_source", "foreign_source", "wrong_quote", "unknown_entry", "stale"]
)
async def test_rebinding_preserves_previous_preview_on_failure(monkeypatch, fault):
    async with TestSessionLocal() as db:
        user, avatar, state, messages, llm = await preview(db, monkeypatch)
        token = state.entity_states[KEY]["token"]
        source_id = "missing-message" if fault == "unknown_source" else messages[2].id
        if fault == "foreign_source":
            db.add(
                ChatMessage(
                    id="foreign-source", session_id="other-session", role="assistant", content=RIGHT
                )
            )
            await db.commit()
            source_id = "foreign-source"
        quote = WRONG if fault == "wrong_quote" else RIGHT
        index = 15 if fault == "unknown_entry" else 1
        if fault == "stale":
            state.entity_states = {**state.entity_states, "changed": True}
        before = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db, state, command(token, source_id, quote, index), user=user, avatar=avatar
        )
        assert "DEBUG ERROR" in result, result
        assert state.entity_states == before
        assert llm.aexecute_complex_task.await_count == 1
