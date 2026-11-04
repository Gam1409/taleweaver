"""Recovery sends bounded facts without dropping IDs, ownership or slicing evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing import recovery, recovery_payload
from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import TEXT, entry


def context():
    actors, snapshot = fixtures()
    snapshot.items["SHIRT"]["image_prompt"] = "unused metadata " * 10000
    return {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
        "limited": False,
        "fingerprint": "original-state-fingerprint",
    }


def test_large_duplicated_item_metadata_is_omitted_but_garment_and_ownership_survive():
    original = context()
    before = deepcopy(original)
    selected, payload = recovery_payload.build_payload(original, True)
    facts = json.loads(payload)
    assert len(payload) < 2000
    assert facts["history"] == original["messages"]
    assert facts["canonical_items"]["SHIRT"]["clothing"]["coverage"] == ["torso"]
    assert facts["canonical_items"]["SHIRT"]["name"] == "Shirt"
    assert facts["owners"] == {"SHIRT": "NPC"}
    assert facts["existing_garments"] == ["SHIRT"]
    assert facts["target_actor"]["worn_item_ids"] == ["SHIRT"]
    assert facts["target_actor"]["age_years"] == 30
    assert "image_prompt" not in payload and "resolved_inventory" not in payload
    assert selected["fingerprint"] == original["fingerprint"]
    assert not selected["limited"]
    assert original == before


def test_budget_drops_oldest_whole_messages_preserving_latest_and_original_fingerprint(monkeypatch):
    original = context()
    _, recent_only = recovery_payload.build_payload(original, True)
    original["messages"].insert(0, {"id": "old", "role": "assistant", "content": "x" * 5000})
    monkeypatch.setattr(recovery_payload, "MAX_PAYLOAD", len(recent_only) + 10)
    selected, payload = recovery_payload.build_payload(original, True)
    assert selected["limited"]
    assert json.loads(payload)["history"] == [original["messages"][1]]
    assert selected["fingerprint"] == original["fingerprint"]
    assert len(original["messages"]) == 2


def test_does_not_call_empty_history_a_success_when_all_messages_exceed_budget(monkeypatch):
    original = context()
    _, empty_payload = recovery_payload.build_payload({**original, "messages": []}, True)
    monkeypatch.setattr(recovery_payload, "MAX_PAYLOAD", len(empty_payload) + 1)
    with pytest.raises(ValueError, match="No complete recent narration fits"):
        recovery_payload.build_payload(original, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget_failure", [False, True])
async def test_preview_with_large_inventory_or_irreducible_budget(monkeypatch, budget_failure):
    original = context()
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        llm = SimpleNamespace(
            model="test",
            aexecute_complex_task=AsyncMock(
                return_value=RecoveryProposal(entries=[entry("source", "NPC")])
            ),
        )
        monkeypatch.setattr(recovery, "recovery_context", AsyncMock(return_value=original))
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        if budget_failure:
            monkeypatch.setattr(recovery_payload, "MAX_PAYLOAD", 10)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview NPC", user=user, avatar=avatar
        )
        preview = state.entity_states[KEY]
        assert preview["context_messages"] == 1
        if budget_failure:
            llm.aexecute_complex_task.assert_not_awaited()
            assert not preview["model_step_started"]
            assert "compact item catalogue" in result and ".." not in result
            assert preview["messages_scanned"] == 0 and not preview["accepted"]
            return
        assert "preview ready" in result, result
        assert preview["messages_scanned"] == 1 and preview["model_step_started"]
        assert len(preview["accepted"]) == 1
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
