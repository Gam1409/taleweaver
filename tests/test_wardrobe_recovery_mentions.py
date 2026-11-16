"""Explicit narration-only underwear mentions cannot disappear without a visible status."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.recovery_mentions import explicit_mentions, mention_checks
from backend.engine.clothing.recovery_schema import OmittedMention, RecoveryProposal
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn
from tests.test_wardrobe_recovery import entry

NARRATION = "Она увидела бельё. Красное. Образ доктора Рин. Стринги."


def context():
    actors, snapshot = fixtures()
    return {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [
            {"id": "source", "role": "assistant", "content": NARRATION},
            {"id": "user", "role": "user", "content": "Лифчик тоже есть."},
        ],
    }


def test_standalone_narrator_mention_is_detected_but_player_assertion_is_not():
    value = context()
    mentions = explicit_mentions(value)
    assert [row["kind"] for row in mentions] == ["underwear_bottom"]
    assert "Стринги." in mentions[0]["sources"][0]["excerpt"]
    assert mention_checks(value, RecoveryProposal())[0]["status"] == "unreviewed"
    proposed = RecoveryProposal(entries=[entry("source", "NPC", "Красные стринги")])
    assert mention_checks(value, proposed)[0]["status"] == "proposed"


def test_explained_omission_needs_an_exact_assistant_source_and_does_not_create_items():
    value = context()
    later = "Доктор передала красные стринги герою."
    value["messages"].append({"id": "later", "role": "assistant", "content": later})
    omitted = OmittedMention(
        kind="underwear_bottom",
        reason="Transferred to the hero.",
        source_message_id="later",
        evidence=later,
    )
    proposal = RecoveryProposal(omitted_mentions=[omitted])
    assert mention_checks(value, proposal)[0]["status"] == "explained"
    assert not proposal.entries
    proposal.omitted_mentions[0].evidence = "An invented transfer."
    assert mention_checks(value, proposal)[0]["status"] == "unreviewed"
    proposal.omitted_mentions[0].source_message_id = "user"
    proposal.omitted_mentions[0].evidence = "Лифчик тоже есть."
    assert mention_checks(value, proposal)[0]["status"] == "unreviewed"


@pytest.mark.asyncio
@pytest.mark.parametrize("responds", [True, False])
async def test_omitted_garment_gets_one_review_then_visible_proposed_or_unreviewed_status(
    monkeypatch, responds
):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=NARRATION, scene_id="START"
        )
        db.add(message)
        await db.commit()
        second = RecoveryProposal()
        if responds:
            garment = entry(message.id, name="Красные стринги")
            garment.action.evidence = NARRATION
            second = RecoveryProposal(entries=[garment])
        llm = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(side_effect=[RecoveryProposal(), second])
        )
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        preview = state.entity_states[KEY]
        assert llm.aexecute_complex_task.await_count == 2
        assert llm.aexecute_complex_task.call_args_list[1].kwargs["phase"] == "evidence_retry"
        assert preview["mention_checks"][0]["status"] == ("proposed" if responds else "unreviewed")
        if not responds:
            assert preview["accepted"] == []
