"""Recovery omissions do not hide evidence failures or discard valid outer layers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery import evaluate
from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_policy import (
    classify_action,
    partition_rejections,
)
from backend.engine.clothing.recovery_prompt import PROMPT
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.engine.narrated_items.errors import ItemFailure
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import TEXT, entry


@pytest.mark.parametrize(
    "name", ["Red panties", "Красные трусики", "Лифчик", "Bra", "Пояс для чулок"]
)
def test_explicit_inner_name_corrects_false_model_flag_without_mutating_input(name):
    candidate = entry("source", name=name).action
    assert not candidate.new_item.clothing.underwear
    assert classify_action(candidate).new_item.clothing.underwear
    assert not candidate.new_item.clothing.underwear


@pytest.mark.parametrize("name", ["Skirt", "Trousers", "Купальник", "Bracers", "Tank top"])
def test_coverage_and_layer_alone_do_not_make_ordinary_clothes_underwear(name):
    candidate = entry("source", name=name).action
    candidate.new_item.clothing.layer = 0
    candidate.new_item.clothing.coverage = ["pelvis", "torso"]
    assert not classify_action(candidate).new_item.clothing.underwear


@pytest.mark.parametrize("invalid_evidence", [False, True])
def test_policy_skip_preserves_other_garments_but_bad_evidence_still_blocks(invalid_evidence):
    actors, snapshot = fixtures()
    inner = entry("source", "NPC", "Panties")
    if invalid_evidence:
        inner.action.evidence = "Not in the narration."
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
    }
    _, accepted, errors, skipped = evaluate(
        context, RecoveryProposal(entries=[entry("source", "NPC"), inner]), False, "session"
    )
    assert len(accepted) == 1
    assert bool(errors) == invalid_evidence
    assert bool(skipped) != invalid_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "small"])
async def test_apply_valid_garments_with_policy_skips_and_selected_model(monkeypatch, role):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=TEXT, scene_id="START"
        )
        db.add(message)
        await db.commit()
        llm = SimpleNamespace(
            model="test",
            aexecute_complex_task=AsyncMock(
                return_value=RecoveryProposal(
                    entries=[entry(message.id), entry(message.id, name="Panties")]
                )
            ),
        )
        selected = []

        def for_role(_user, name):
            selected.append(name)
            return llm

        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", for_role)
        monkeypatch.setattr(recovery, "detail_settings", lambda _: {"detailed": False})
        command = "wardrobe_preview LINA" + (f" {role}" if role else "")
        result = await DebugEngine.handle_debug_command(
            db, state, command, user=user, avatar=avatar
        )
        assert "preview ready" in result
        preview = state.entity_states[KEY]
        assert preview["skipped"] and not preview["errors"] and len(preview["accepted"]) == 1
        assert selected == [role or "complex"]
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "Recovered 1" in result
        assert not any(
            item.get("name") == "Panties"
            for item in state.entity_states["LINA"]["inventory"]
            if isinstance(item, dict)
        )


def test_prompt_is_history_specific_and_disambiguates_missing_records():
    assert "missing FROM THE RECORDS" in PROMPT
    assert "basis=completed and disposition=carried" in PROMPT
    assert "never restate the task" in PROMPT
    assert "completed_narration" not in PROMPT
    assert "authoritative_resolution" not in PROMPT


@pytest.mark.parametrize(
    "detailed,age,reasons",
    [
        (False, 30, ["tracking is disabled"]),
        (True, None, ["age is not recorded"]),
        (False, None, ["tracking is disabled", "age is not recorded"]),
        (True, 17, ["age is 17"]),
    ],
)
def test_policy_skip_names_actual_unmet_requirements(detailed, age, reasons):
    errors, skipped = partition_rejections(
        [
            ItemFailure("Named garment", "Policy wording can change", "inner_creation_policy"),
            ItemFailure("Other garment", "bad source"),
        ],
        detailed=detailed,
        age=age,
    )
    assert errors == ["Other garment: bad source"]
    assert len(skipped) == 1 and skipped[0].startswith("Named garment: ")
    assert all(reason in skipped[0] for reason in reasons)
    assert ("tracking is disabled" in skipped[0]) == (not detailed)
    assert ("age is not recorded" in skipped[0]) == (age is None)


def test_policy_classification_never_parses_a_human_error_suffix():
    from backend.engine.narrated_items.errors import NEW_INNER_CLOTHING

    errors, skipped = partition_rejections(
        [ItemFailure("Misleading name", NEW_INNER_CLOTHING)], detailed=False, age=None
    )
    assert errors == [f"Misleading name: {NEW_INNER_CLOTHING}"] and not skipped


def test_duplicate_policy_skips_are_displayed_once():
    actors, snapshot = fixtures()
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
    }
    candidate = entry("source", "NPC", "Panties")
    _, accepted, errors, skipped = evaluate(
        context, RecoveryProposal(entries=[candidate, candidate]), False, "session"
    )
    assert not accepted and not errors
    assert len(skipped) == 1 and "tracking is disabled" in skipped[0]
