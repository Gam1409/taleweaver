"""Narration-only garments are new records, never references to invented item IDs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_contract import response_schema
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.engine.visual_novel.continuity import Possessions
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import entry


def test_new_items_must_include_garment_metadata_in_runtime_and_wire_schema():
    validator = Draft202012Validator(RecoveryProposal.model_json_schema())
    for new_item in [
        {"name": "Coat", "description": "A white coat", "kind": "ordinary"},
        {"name": "Coat", "description": "A white coat", "kind": "clothing"},
    ]:
        row = entry("source").model_dump()
        row["action"]["new_item"] = new_item
        wire = {"entries": [row]}
        assert list(validator.iter_errors(wire))
        with pytest.raises(ValidationError):
            RecoveryProposal.model_validate(wire)


def test_existing_ids_are_limited_to_owned_valid_garments():
    actors, snapshot = fixtures()
    snapshot.items["CUP"] = {"id": "CUP", "name": "Cup"}
    snapshot.owners["CUP"] = "NPC"
    snapshot.items["OTHER_SHIRT"] = {**snapshot.items["SHIRT"], "id": "OTHER_SHIRT"}
    snapshot.owners["OTHER_SHIRT"] = "__player__"
    model = response_schema({"actor": actors["NPC"], "snapshot": snapshot})
    validator = Draft202012Validator(model.model_json_schema())
    for identifier in ["SHIRT", "CUP", "OTHER_SHIRT", "imagined_id"]:
        row = entry("source", "NPC").model_dump()
        row["action"].update(new_item=None, item_id=identifier)
        wire = {"entries": [row]}
        assert bool(list(validator.iter_errors(wire))) == (identifier != "SHIRT")
        if identifier == "SHIRT":
            model.model_validate(wire)
            continue
        with pytest.raises(ValidationError):
            model.model_validate(wire)


@pytest.mark.asyncio
async def test_narration_only_outfit_with_no_clothing_records_is_created_after_review(monkeypatch):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        state.entity_states = {
            **(state.entity_states or {}),
            "LINA": {
                "inventory": [],
                "visual_profile": {"appearance": {"age_years": 30}, "worn": []},
            },
        }
        text = "Lina wears a coat, shirt, skirt, scarf, stockings, gloves, hat and boots."
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=text, scene_id="START"
        )
        db.add(message)
        await db.commit()
        before = deepcopy(state.entity_states)
        entries = []
        for name in ["Coat", "Shirt", "Skirt", "Scarf", "Stockings", "Gloves", "Hat", "Boots"]:
            row = entry(message.id, "LINA", name).model_dump()
            row["action"]["evidence"] = text
            entries.append(row)
        invalid = deepcopy(entries)
        for row in invalid:
            row["action"].update(item_id="fake_" + row["action"]["new_item"]["name"], new_item=None)
        llm = SimpleNamespace(
            model="test",
            aexecute_complex_task=AsyncMock(
                side_effect=[
                    {"entries": invalid},
                    {"entries": entries},
                ]
            ),
        )
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA small", user=user, avatar=avatar
        )
        assert "8 proposed changes" in result, result
        preview = state.entity_states[KEY]
        assert not preview["errors"]
        assert state.entity_states["LINA"] == before["LINA"]
        assert llm.aexecute_complex_task.await_count == 2
        schema = llm.aexecute_complex_task.call_args_list[0].args[2].model_json_schema()
        assert "OwnedRecoveryAction" not in schema.get("$defs", {})
        assert all(row["item"]["id"].startswith("item_") for row in preview["accepted"])
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "Recovered 8" in result, result
        assert len(state.entity_states["LINA"]["inventory"]) == 8
        assert len(state.entity_states["LINA"]["visual_profile"]["worn"]) == 8


def test_unknown_id_and_unstructured_existing_item_have_distinct_named_errors():
    from backend.engine.clothing.recovery_contract import resolve_garment
    from backend.engine.narrated_items.schema import ItemAction

    action = ItemAction(
        item_id="COAT",
        source_owner="NPC",
        destination_owner="NPC",
        disposition="worn",
        basis="observed_wear",
        evidence="A coat is worn.",
    )
    with pytest.raises(ValueError, match="Unknown garment ID 'COAT'"):
        resolve_garment(action, Possessions(), "NPC")
    snapshot = Possessions(
        items={"COAT": {"id": "COAT", "name": "White coat"}}, owners={"COAT": "NPC"}
    )
    with pytest.raises(
        ValueError, match=r"White coat \[COAT\].*missing or invalid clothing metadata"
    ):
        resolve_garment(action, snapshot, "NPC")
