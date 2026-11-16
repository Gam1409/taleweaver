"""Evidence repair preserves validated garments and keeps unresolved facts inspectable."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery import evaluate
from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_request import ProposalReview, request_proposal
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import PRIOR, seed_vn
from tests.test_wardrobe_recovery import TEXT, entry


def test_rejections_identify_basis_quote_and_partial_region_failures_without_mutation():
    actors, snapshot = fixtures()
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
    }
    before = deepcopy(context)
    wrong_basis = entry("source", "NPC", "Claimed shirt")
    wrong_basis.action.basis = "claim"
    wrong_quote = entry("source", "NPC", "Paraphrased skirt")
    wrong_quote.action.evidence = "A completely different sentence."
    displaced = entry("source", "NPC", "Displaced coat")
    displaced.uncovered_regions = ["feet"]
    displaced.placement_evidence = "No such placement quote."
    proposal = RecoveryProposal(
        entries=[entry("source", "NPC"), wrong_basis, wrong_quote, displaced]
    )
    diagnostics = []
    _, accepted, errors, _ = evaluate(context, proposal, True, "session", diagnostics=diagnostics)
    assert len(accepted) == 1 and len(diagnostics) == 3
    assert "basis 'claim'" in diagnostics[0]["reasons"][0]
    assert "not an exact contiguous substring" in diagnostics[1]["reasons"][0]
    assert "outside garment coverage" in diagnostics[2]["reasons"][0]
    assert "Placement quote" in diagnostics[2]["reasons"][1]
    assert diagnostics[1]["evidence"] == wrong_quote.action.evidence
    assert diagnostics[2]["coverage"] == ["torso", "arms"]
    assert errors and context == before
    assert evaluate(context, proposal, True, "session")[1] == accepted


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", ["fixed", "still_wrong", "drops_valid"])
async def test_evidence_retry_retains_valid_entries_and_exposes_unresolved_sources(
    monkeypatch, correction
):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, previous_id = await seed_vn(db)
        state.is_debug_enabled = True
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=TEXT, scene_id="START"
        )
        db.add(message)
        await db.commit()
        first = RecoveryProposal(entries=[entry(message.id), entry(message.id, name="Scarf")])
        first.entries[1].action.evidence = "Paraphrased clothing description."
        second = first.model_copy(deep=True)
        if correction != "still_wrong":
            second.entries[1].action.evidence = TEXT
        if correction == "drops_valid":
            second.entries = second.entries[1:]
        llm = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(side_effect=[first, second])
        )
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "preview ready" in result, result
        assert llm.aexecute_complex_task.await_count == 2
        assert llm.aexecute_complex_task.call_args_list[1].kwargs["phase"] == "evidence_retry"
        preview = state.entity_states[KEY]
        if correction == "fixed":
            assert len(preview["accepted"]) == 2 and not preview["errors"]
            applied = await DebugEngine.handle_debug_command(
                db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
            )
            assert "Recovered 2" in applied
            return
        assert len(preview["accepted"]) == 1 and preview["errors"]
        assert preview["rejected_entries"][0]["label"] == "Scarf"
        assert preview["rejected_entries"][0]["evidence"] == "Paraphrased clothing description."
        assert preview["rejected_sources"] == {previous_id: PRIOR, message.id: TEXT}
        applied = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "nothing was applied" in applied


@pytest.mark.asyncio
async def test_schema_retry_consumes_the_same_single_retry_budget():
    llm = SimpleNamespace(
        model="test",
        aexecute_complex_task=AsyncMock(
            side_effect=[
                {"entries": [{"source_message_id": "source"}]},
                RecoveryProposal(),
            ]
        ),
    )
    checked = []

    def review(_value):
        checked.append(True)
        return ProposalReview(errors=["Evidence would fail"], preserved_entries=[])

    await request_proposal(llm, "Instructions", "{}", RecoveryProposal, "session", review=review)
    assert llm.aexecute_complex_task.await_count == 2
    assert checked == []
