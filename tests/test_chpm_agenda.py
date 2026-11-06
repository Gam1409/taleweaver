"""Declared intentions survive transcript eviction, never become world outcomes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.engine.chpm import agenda, memory, rendering, runtime
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import (
    AgendaEntry,
    AgendaEvidence,
    AgendaIntent,
    KernelState,
    SpokenEvidence,
    Verdict,
)
from backend.engine.chpm.state import KEY, load, retract
from tests.test_chpm_kernel import decision
from tests.test_chpm_memory import entry, source
from tests.test_chpm_runtime import prepared


def undertaking(actor="npc", identifier="goal", text="Repair the bridge"):
    return AgendaEntry(
        id=identifier,
        actor_id=actor,
        kind="commitment",
        text=text,
        source=entry(observer=actor),
    )


def selected(action="commitment", entry_id=None):
    chosen = decision()
    chosen.selected.agenda_change = AgendaIntent(
        action=action, text="Repair the bridge", entry_id=entry_id
    )
    return {"npc": chosen}


def review(quote="I will repair the bridge."):
    evidence = AgendaEvidence(actor_id="npc", quote=quote)
    return Verdict(matches=True, evidence=[evidence], agenda_evidence=[evidence])


def test_create_close_and_idempotence_do_not_mutate_inputs():
    original = []
    reply = source(content="I will repair the bridge.")
    created = agenda.apply(original, selected(), review(), reply)
    assert original == []
    assert len(created) == 1 and created[0].closure is None
    assert created[0].source.source_message_id == reply.id
    assert agenda.apply(created, selected(), review(), reply) == created
    closed_reply = source("done", "I repaired the bridge.")
    intent = selected("report_done", created[0].id)
    closed = agenda.apply(created, intent, review(closed_reply.content), closed_reply)
    assert created[0].closure is None
    assert closed[0].closure.reason == "report_done"
    assert agenda.context(closed) == []
    assert agenda.apply(closed, intent, review(closed_reply.content), closed_reply) == closed


@pytest.mark.parametrize("case", ["missing", "extra", "foreign", "narrator", "empty", "duplicate"])
def test_review_requires_exact_selected_change_and_own_spoken_quote(case):
    verdict = review()
    decisions = selected()
    if case == "missing":
        verdict.agenda_evidence = []
    elif case == "extra":
        decisions["npc"].selected.agenda_change = None
    elif case == "foreign":
        verdict.agenda_evidence[0] = SpokenEvidence(
            actor_id="other", quote="I will repair the bridge."
        )
    elif case == "narrator":
        verdict.agenda_evidence[0] = SpokenEvidence(
            actor_id="npc", quote="She promised the player."
        )
    elif case == "empty":
        verdict.agenda_evidence[0] = SpokenEvidence(actor_id="npc", quote="")
    else:
        verdict.agenda_evidence *= 2
    with pytest.raises(ChpmError):
        agenda.validate_evidence(decisions, verdict)


@pytest.mark.parametrize("case", ["unknown", "wrong-text", "closed", "foreign"])
def test_closure_targets_only_the_owned_active_exact_entry(case):
    entries = [undertaking()]
    intent = AgendaIntent(action="withdraw", text="Repair the bridge", entry_id="goal")
    if case == "unknown":
        intent.entry_id = "invented"
    elif case == "wrong-text":
        intent.text = "Hand over the key"
    elif case == "foreign":
        entries = [undertaking(actor="other")]
    else:
        entries = agenda.apply(
            entries,
            selected("withdraw", "goal"),
            review(),
            source(content="I will repair the bridge."),
        )
    choices = selected()
    choices["npc"].selected.agenda_change = intent
    with pytest.raises(ChpmError):
        agenda.apply(entries, choices, review(), source("new", "I will repair the bridge."))


def test_ledger_is_independent_of_zero_memory_and_retracts_creation_or_closure():
    record = undertaking()
    closed = agenda.apply(
        [record],
        selected("withdraw", "goal"),
        review(),
        source("withdrawal", "I will repair the bridge."),
    )
    state = KernelState(agenda=closed)
    state.settings.memory_limit = 0
    memory.append(state, "npc", [entry()])
    assert state.memories["npc"] == [] and state.agenda == closed
    host = SimpleNamespace(entity_states={KEY: state.model_dump(), "world": {"quest": "open"}})
    retract(host, "withdrawal")
    assert load(host).agenda[0].closure is None
    retract(host, "message")
    assert load(host).agenda == []
    assert host.entity_states["world"] == {"quest": "open"}


async def test_source_recheck_reopens_invalid_closure_and_drops_invalid_creation():
    original = source()
    closing = source("withdrawal", "I will repair the bridge.")
    records = agenda.apply([undertaking()], selected("withdraw", "goal"), review(), closing)
    host = SimpleNamespace(
        game_id="session", db=SimpleNamespace(scalars=AsyncMock(return_value=[original, closing]))
    )
    assert await agenda.recall(host, "npc", records) == records
    closing.revision_id = "edited"
    assert (await agenda.recall(host, "npc", records))[0].closure is None
    original.content = "Replaced source"
    assert await agenda.recall(host, "npc", records) == []


def test_caps_fail_without_silent_deletion_and_repeated_promises_do_not_duplicate():
    intent = AgendaIntent(action="goal", text="A new goal")
    active = [undertaking(identifier=str(i), text=str(i)) for i in range(8)]
    with pytest.raises(ChpmError, match="full"):
        agenda.validate_intent(intent, active)
    with pytest.raises(ChpmError, match="duplicates"):
        agenda.validate_intent(
            AgendaIntent(action="goal", text="Repair the bridge"), [undertaking()]
        )
    full = [undertaking(actor=f"other-{i}", identifier=str(i)) for i in range(256)]
    with pytest.raises(ChpmError, match="archive is full"):
        agenda.apply(full, selected(), review(), source(content="I will repair the bridge."))
    assert len(full) == 256


def test_schema_rejects_player_claim_as_commitment_source():
    raw = undertaking().model_dump()
    raw["source"]["source_role"] = "user"
    with pytest.raises(ValidationError):
        AgendaEntry.model_validate(raw)
    with pytest.raises(ValidationError):
        AgendaIntent(action="goal", text="Goal", entry_id="existing")
    with pytest.raises(ValidationError):
        AgendaIntent(action="withdraw", text="Goal")


async def test_review_failure_publishes_no_ledger_change(monkeypatch):
    host = prepared()
    host._chpm_turn.decisions = selected()
    verdict = review()
    verdict.agenda_evidence = []
    monkeypatch.setattr(rendering.inference, "request", AsyncMock(return_value=verdict))
    with pytest.raises(ChpmError, match="exactly"):
        await rendering.validate(
            host, "I will repair the bridge.", completed=True, resolution="", system_prompt="Policy"
        )
    assert load(host.state).agenda == []
    with pytest.raises(ChpmError):
        runtime.finish(host, source(content="I will repair the bridge."), completed=True)
    assert load(host.state).agenda == []


def test_only_selected_candidate_can_create_an_entry_and_defer_cannot_change_it():
    choices = selected("goal")
    choices["npc"].proposal.candidates[1].agenda_change = AgendaIntent(
        action="commitment", text="Unselected promise"
    )
    records = agenda.apply([], choices, review(), source(content="I will repair the bridge."))
    assert [record.kind for record in records] == ["goal"]
    assert records[0].text == "Repair the bridge"
    with pytest.raises(ChpmError, match="silent DEFER"):
        agenda.validate_proposal(choices["npc"].proposal, [])


async def test_other_actors_agenda_never_enters_individual_context():
    record = undertaking(actor="other")
    host = SimpleNamespace(game_id="session", db=SimpleNamespace(scalars=AsyncMock()))
    assert await agenda.recall(host, "npc", [record]) == []
    host.db.scalars.assert_not_called()


def test_batch_is_atomic_if_later_actor_has_invalid_target():
    original = [undertaking()]
    choices = selected("withdraw", "goal")
    foreign = decision().model_copy(update={"actor_id": "other"}, deep=True)
    foreign.selected.agenda_change = AgendaIntent(
        action="withdraw", text="Repair the bridge", entry_id="goal"
    )
    choices["other"] = foreign
    verdict = review()
    spoken = AgendaEvidence(actor_id="other", quote="I withdraw.")
    verdict.evidence.append(spoken)
    verdict.agenda_evidence.append(spoken)
    with pytest.raises(ChpmError):
        agenda.apply(
            original, choices, verdict, source(content="I will repair the bridge. I withdraw.")
        )
    assert original[0].closure is None
