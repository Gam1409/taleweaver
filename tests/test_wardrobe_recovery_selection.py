"""Explicit selection restores only checked validated garments despite other rejections."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.clothing.recovery_selection import selected_entries
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import entry


@pytest.mark.parametrize("selection", ["1", "0,0", "0,1", "-1", "", "1.0", "0,", "9" * 100])
def test_selection_cannot_include_rejected_duplicates_or_malformed_indices(selection):
    preview = {
        "accepted": [{"proposal_index": 0}, {"proposal_index": 2}],
        "errors": ["Rejected index 1"],
    }
    with pytest.raises(ValueError):
        selected_entries(preview, selection)
    assert selected_entries(preview, "2") == {2}


@pytest.mark.asyncio
async def test_selecting_later_entry_uses_same_id_and_preserves_unselected_and_rejected_items(
    monkeypatch,
):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        text = "Лина носит халат и шарф."
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=text, scene_id="START"
        )
        db.add(message)
        await db.commit()
        coat = entry(message.id)
        coat.action.evidence = text
        invalid = entry(message.id, name="Unsupported shoes")
        invalid.action.evidence = "This quote does not exist."
        scarf = entry(message.id, name="Шарф")
        scarf.action.evidence = text
        proposal = RecoveryProposal(entries=[coat, invalid, scarf])
        llm = SimpleNamespace(model="test", aexecute_complex_task=AsyncMock(return_value=proposal))
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        preview = state.entity_states[KEY]
        assert preview["errors"] and [row["proposal_index"] for row in preview["accepted"]] == [
            0,
            2,
        ]
        expected = preview["accepted"][1]["item"]["id"]
        rejected = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"] + " 1", user=user, avatar=avatar
        )
        assert "nothing was applied" in rejected
        restored = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"] + " 2", user=user, avatar=avatar
        )
        assert "Recovered 1" in restored, restored
        inventory = state.entity_states["LINA"]["inventory"]
        recovered = [
            row for row in inventory if isinstance(row, dict) and row.get("id") == expected
        ]
        assert len(recovered) == 1 and recovered[0]["name"] == "Шарф"
        names = {row.get("name") for row in inventory if isinstance(row, dict)}
        assert "Синий халат" not in names and "Unsupported shoes" not in names


def test_old_preview_requires_regeneration_and_selection_is_nonempty():
    with pytest.raises(ValueError, match="predates item selection"):
        selected_entries({"accepted": [{"item": {}}]}, "0")
    with pytest.raises(ValueError):
        selected_entries({"accepted": []}, "0")
