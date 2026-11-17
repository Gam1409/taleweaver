"""Closure repair feedback identifies the owned reference without inventing dialogue."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agenda
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaClosure, AgendaIntent
from tests.test_chpm_agenda import undertaking


def test_wrong_closure_text_reports_exact_active_text_and_keeps_dialogue_separate():
    entries = [undertaking()]
    before = deepcopy(entries)
    intent = AgendaIntent(action="report_done", entry_id="goal", text="I finished my work.")

    with pytest.raises(ChpmError) as captured:
        agenda.validate_intent(intent, entries)

    message = str(captured.value)
    assert "active owned entry exactly" in message
    assert '"Repair the bridge"' in message
    assert "message_plan" in message and "legacy: intention" in message
    assert entries == before and intent.text == "I finished my work."


@pytest.mark.parametrize("action", ["withdraw", "report_done"])
def test_unknown_id_feedback_identifies_active_ids_without_reopening_closed_entries(action):
    active = undertaking(identifier="active")
    closed = undertaking(identifier="closed")
    closed.closure = AgendaClosure(reason="report_done", source=closed.source)
    entries = [active, closed]
    before = deepcopy(entries)
    intent = AgendaIntent(action=action, entry_id="unknown", text=active.text)

    with pytest.raises(ChpmError) as captured:
        agenda.validate_intent(intent, entries)

    message = str(captured.value)
    assert "entry_id" in message
    assert '"active"' in message and '"closed"' not in message
    assert entries == before


def test_correct_closure_reference_still_needs_no_repair_or_text_rewriting():
    entry = undertaking()
    for action in ("withdraw", "report_done"):
        intent = AgendaIntent(action=action, entry_id=entry.id, text=entry.text)
        before = intent.model_dump()
        assert agenda.validate_intent(intent, [entry]) is None
        assert intent.model_dump() == before and entry.closure is None


async def test_exact_reference_hint_reaches_the_existing_single_proposal_repair():
    import json

    from backend.engine.chpm import motivation, proposal_attempt
    from backend.engine.chpm.proposal_draft import Draft
    from backend.engine.chpm.schema import Settings, Usage
    from tests.chpm_repair_fixture import corrections
    from tests.test_chpm_kernel import wire_proposal
    from tests.test_chpm_reliability import Replies
    from tests.test_chpm_semantic_choice import fixture

    entries = [undertaking()]
    value, window, _, _ = fixture()
    catalogue = motivation.build(value, [], window)
    original = wire_proposal()
    intent = {"action": "withdraw", "entry_id": "goal", "text": "I withdraw from this work."}
    original["candidates"]["CONTINUE"]["agenda_change"] = intent
    corrected = {**intent, "text": entries[0].text}
    model = Replies(
        [
            json.dumps(original),
            corrections(("/candidates/CONTINUE/agenda_change", corrected)),
        ]
    )
    host = SimpleNamespace(game_id="fixture", _chpm_model_factory=lambda _role: model)
    usage = Usage()

    def accept(candidate):
        agenda.validate_proposal(candidate.materialize(catalogue).canonical(), entries)
        return candidate

    result = await proposal_attempt.request(
        host,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {},
        Draft,
        {},
        accept,
    )

    assert result.candidates["CONTINUE"].agenda_change.text == entries[0].text
    feedback = model.requests[1][2]["proposal_feedback"]
    assert '"Repair the bridge"' in feedback["error"]
    assert feedback["rejected_proposal"]["candidates"]["CONTINUE"]["agenda_change"] == intent
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert entries[0].closure is None and len(model.requests) == 2
