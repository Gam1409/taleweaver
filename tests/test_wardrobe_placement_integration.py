"""Existing garment placement survives the real debug preview/apply boundary."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.recovery_contract import existing_garments
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn


@pytest.mark.asyncio
@pytest.mark.parametrize("restore", [False, True])
async def test_preview_and_apply_existing_worn_placement(monkeypatch, restore):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        actor = fixtures()[0]["NPC"]
        npc.age_years = 30
        npc.inventory = deepcopy(actor["inventory"])
        npc.visual_profile = deepcopy(actor["visual_profile"])
        npc.visual_profile["worn"][0]["uncovered_regions"] = ["torso"] if restore else []
        before = deepcopy(npc.visual_profile)
        text = "Lina lowers her shirt again." if restore else "Lina lifts her shirt."
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=text, scene_id="START"
        )
        db.add(message)
        await db.commit()
        context = await recovery_context(db, state, avatar, "LINA")
        assert context["snapshot"].owners.get("SHIRT") == "LINA", context["snapshot"].owners
        assert "SHIRT" in existing_garments(context), context["snapshot"].items.get("SHIRT")
        proposal = RecoveryProposal.model_validate(
            {
                "entries": [
                    {
                        "source_message_id": message.id,
                        "action": {
                            "item_id": "SHIRT",
                            "source_owner": "LINA",
                            "destination_owner": "LINA",
                            "basis": "observed_wear",
                            "disposition": "worn",
                            "evidence": text,
                        },
                        "uncovered_regions": [] if restore else ["torso"],
                        "restore_coverage": restore,
                        "placement_evidence": text,
                    }
                ]
            }
        )
        llm = SimpleNamespace(model="test", aexecute_complex_task=AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            "backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: llm
        )
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "preview ready" in result, result
        assert npc.visual_profile == before and "LINA" not in state.entity_states
        preview = state.entity_states[KEY]
        assert len(preview["accepted"]) == 1
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
        await db.commit()
        await db.refresh(state)
        saved = state.entity_states["LINA"]
        assert len(saved["inventory"]) == 1 and saved["inventory"][0]["id"] == "SHIRT"
        worn = saved["visual_profile"]["worn"]
        assert len(worn) == 1 and worn[0]["item_id"] == "SHIRT"
        assert worn[0]["uncovered_regions"] == ([] if restore else ["torso"])
        assert KEY not in state.entity_states
