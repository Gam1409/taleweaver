"""History recovery registers ordinary body items and explicitly selected player corrections."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select

from backend.engine.clothing.recovery import evaluate
from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_contract import response_schema
from backend.engine.clothing.recovery_correction import RecoveryCorrection, _corrected_proposal
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryProposal
from backend.engine.clothing.wear_provenance import remap_profile
from backend.engine.debug_engine import DebugEngine
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_cards.current_state import character_current_state
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn

TEXT = "Лина держит запечатанную пробирку во влагалище."


def body_entry(source="source", npc="NPC", **changes):
    action = {
        "source_owner": npc,
        "destination_owner": npc,
        "disposition": "worn",
        "basis": "observed_wear",
        "evidence": TEXT,
        "attachment_slot": "vaginal",
        "new_item": {
            "name": "Запечатанная пробирка",
            "description": "Небольшая закрытая стеклянная пробирка.",
            "kind": "ordinary",
        },
        **changes,
    }
    return RecoveryEntry(source_message_id=source, action=ItemAction(**action))


def context(*, role="assistant", allow_player=False):
    actors, snapshot = fixtures()
    return {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": role, "content": TEXT}],
        "allow_player_sources": allow_player,
    }


def test_missing_body_item_uses_one_canonical_inventory_record_and_the_original_source():
    original = context()
    before = deepcopy(original["actor"])
    proposed = body_entry()
    schema = response_schema(original)
    wire = {"entries": [proposed.model_dump()]}
    assert Draft202012Validator(schema.model_json_schema()).is_valid(wire)
    changed, accepted, errors, _ = evaluate(original, schema.model_validate(wire), True, "session")
    assert not errors and len(accepted) == 1
    item = accepted[0]["item"]
    assert item["item_type"] == "DEFAULT" and not item.get("clothing")
    assert item["item_origin"]["source_message_id"] == "source"
    placement = next(
        row for row in changed["NPC"]["visual_profile"]["worn"] if row["item_id"] == item["id"]
    )
    assert placement["attachment_slot"] == "vaginal"
    assert placement["source"]["source_message_id"] == "source"
    assert placement["source"]["evidence"] == TEXT
    assert original["actor"] == before


@pytest.mark.parametrize("age,slots", [(None, None), (17, None), (30, []), (30, ["anal"])])
def test_recovery_keeps_age_and_explicit_body_availability_checks(age, slots):
    original = context()
    original["actor"]["age_years"] = age
    original["actor"]["visual_profile"]["body"] = {"form": "humanoid", "attachment_slots": slots}
    changed, accepted, errors, _ = evaluate(
        original, RecoveryProposal(entries=[body_entry()]), True, "session"
    )
    assert errors and not accepted and changed["NPC"]["inventory"] == original["actor"]["inventory"]


@pytest.mark.parametrize("role,allowed", [("assistant", True), ("user", False)])
def test_player_sources_are_not_accepted_by_legacy_or_automatic_callers(role, allowed):
    _, accepted, errors, _ = evaluate(
        context(role=role), RecoveryProposal(entries=[body_entry()]), True, "session"
    )
    assert bool(accepted) is allowed and bool(errors) is not allowed


def test_player_description_can_restore_stockings_only_in_the_explicit_debug_context():
    text = "Доктор Рин носит белые чулки."
    original = context(role="user", allow_player=True)
    original["messages"][0]["content"] = text
    proposal = RecoveryEntry(
        source_message_id="source",
        action=ItemAction(
            source_owner="NPC",
            destination_owner="NPC",
            basis="observed_wear",
            disposition="worn",
            evidence=text,
            new_item={
                "kind": "clothing",
                "name": "Белые чулки",
                "description": "Белые тканевые чулки.",
                "clothing": {"layer": 0, "coverage": ["legs", "feet"]},
                "wearable_slots": ["Legs"],
            },
        ),
    )
    changed, accepted, errors, _ = evaluate(
        original, RecoveryProposal(entries=[proposal]), True, "session"
    )
    assert len(accepted) == 1 and not errors
    assert accepted[0]["source_role"] == "user"
    item = accepted[0]["item"]
    assert item["clothing_origin"]["source_role"] == "user"
    assert item["item_origin"]["source_message_id"] == "source"
    assert any(row["item_id"] == item["id"] for row in changed["NPC"]["visual_profile"]["worn"])


def test_existing_ordinary_item_is_reused_and_cannot_be_taken_from_another_owner():
    original = context()
    item = {"id": "TUBE", "name": "Пробирка"}
    original["actor"]["inventory"].append(item)
    original["actor"]["resolved_inventory"].append(item)
    original["snapshot"].items["TUBE"] = item
    original["snapshot"].owners["TUBE"] = "NPC"
    row = body_entry(item_id="TUBE", new_item=None)
    changed, accepted, errors, _ = evaluate(
        original, RecoveryProposal(entries=[row]), True, "session"
    )
    assert accepted and not errors
    assert len([item for item in changed["NPC"]["inventory"] if item.get("id") == "TUBE"]) == 1
    original["snapshot"].owners["TUBE"] = "__player__"
    _, accepted, errors, _ = evaluate(original, RecoveryProposal(entries=[row]), True, "session")
    assert errors and not accepted


def test_body_quote_correction_and_copied_player_provenance_remain_bound_to_the_source():
    original = context(role="user", allow_player=True)
    proposed = body_entry()
    proposed.action.evidence = "A paraphrase."
    preview = {
        "proposal": RecoveryProposal(entries=[proposed]).model_dump(),
        "rejected_entries": [{"index": 0}],
    }
    correction = RecoveryCorrection(status="worn", evidence=TEXT, attachment_slot="vaginal")
    corrected = _corrected_proposal(preview, 0, correction)
    changed, accepted, errors, _ = evaluate(original, corrected, True, "session")
    assert accepted and not errors
    copied = remap_profile(changed["NPC"]["visual_profile"], {"source": "copied-source"})
    proof = next(row["source"] for row in copied["worn"] if row.get("attachment_slot"))
    assert proof["source_role"] == "user" and proof["source_message_id"] == "copied-source"


async def test_player_source_preview_needs_selection_and_occupied_slot_survives_reload(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.age_years, npc.npc_type, npc.gender = 30, "HUMANOID", "Female"
        message = ChatMessage(
            session_id=state.session_id, role="user", content=TEXT, scene_id="START"
        )
        db.add(message)
        await db.commit()
        proposal = RecoveryProposal(entries=[body_entry(message.id, "LINA")])
        llm = SimpleNamespace(model="mock", aexecute_complex_task=AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            "backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: llm
        )
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "preview ready" in result
        preview = deepcopy(state.entity_states[KEY])
        assert not (state.entity_states.get("LINA") or {}).get("visual_profile")
        assert preview["accepted"][0]["source_role"] == "user"
        result = await DebugEngine.handle_debug_command(
            db, state, f"wardrobe_apply {preview['token']}", user=user, avatar=avatar
        )
        assert "explicit selection" in result
        result = await DebugEngine.handle_debug_command(
            db, state, f"wardrobe_apply {preview['token']} 0", user=user, avatar=avatar
        )
        assert "Recovered 1" in result, result
        await db.commit()
        await db.refresh(state)
        current = await character_current_state(db, state, npc)
        item = next(
            row for row in current["clothing"]["items"] if row["name"] == "Запечатанная пробирка"
        )
        assert item["slots"] == ["BodyVaginal"]
        # Editing the cited player source retracts its displayed placement, not ownership.
        message.content = "An edited source."
        await db.commit()
        current = await character_current_state(db, state, npc)
        assert not any("BodyVaginal" in row["slots"] for row in current["clothing"]["items"])
        assert any(
            row.get("id") == item["item_id"] for row in state.entity_states["LINA"]["inventory"]
        )
