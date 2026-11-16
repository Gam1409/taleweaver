"""Denied movement cannot return as completed through optional derived contexts."""

from types import SimpleNamespace

import pytest

from backend.engine.chpm import causal_memory, passages, recovery_perception, recovery_queue
from backend.engine.chpm.schema import KernelState, Verdict
from backend.engine.narrated_movement.runtime import _event, complete, finish
from tests.test_chpm_causal_memory import draft
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_host_state import mind
from tests.test_chpm_memory import source
from tests.test_chpm_movement_feedback import TEXT, audit, outcome
from tests.test_narrated_movement_guards import move, pending


@pytest.mark.parametrize("status", ["applied", "blocked", "unconfirmed"])
def test_causal_notes_cannot_recertify_denied_departure_but_keep_independent_fact(status):
    turn, observer = contract_fixture()
    text = TEXT + "\nRin folds her map and puts it on the bench."
    reply = source("mixed", text)
    independent = draft(text)
    independent["actor_id"] = "other"
    turn.decisions["other"] = turn.decisions["npc"].model_copy(update={"actor_id": "other"})
    for fact in independent["facts"].values():
        fact["passage_id"] = "p1"
    turn.verdict = Verdict(matches=True, causal_updates=[draft(text), independent])
    saved = KernelState(minds={"npc": observer, "other": mind("other")})
    causal_memory.apply(
        turn, saved, reply, passages.index(text), movement_outcomes=(outcome(status),)
    )
    assert ("npc" in saved.causal_memory.actors) is (status == "applied")
    assert (
        saved.causal_memory.actors["other"][0].origin.quote
        == "Rin folds her map and puts it on the bench."
    )
    assert bool(saved.usage.causal_notes) is (status != "applied")


def test_other_observer_cannot_record_the_same_denied_movement_as_completed():
    turn, observer = contract_fixture()
    turn.decisions["other"] = turn.decisions["npc"].model_copy(update={"actor_id": "other"})
    turn.verdict = Verdict(matches=True, causal_updates=[draft(TEXT, actor="other")])
    saved = KernelState(minds={"npc": observer, "other": mind("other")})
    reply = source("denied", TEXT)
    causal_memory.apply(turn, saved, reply, passages.index(TEXT), movement_outcomes=(outcome(),))
    assert not saved.causal_memory.actors and saved.usage.causal_notes


def test_mixed_same_passage_note_is_conservatively_deferred_without_erasing_prior_threads():
    turn, observer = contract_fixture()
    reply = source("mixed", "Rin walks into the annex while folding her map.")
    turn.verdict = Verdict(matches=True, causal_updates=[draft(reply.content)])
    saved = KernelState(minds={"npc": observer})
    causal_memory.apply(
        turn,
        saved,
        reply,
        passages.index(reply.content),
        movement_outcomes=(outcome(text=reply.content),),
    )
    # A broad optional note cannot safely separate these effects without new evidence.
    assert not saved.causal_memory.actors and saved.minds["npc"] == observer


@pytest.mark.parametrize("case", ["locked", "invalid", "ambiguous", "unconfirmed"])
def test_owner_distinguishes_rule_denial_from_invalid_or_uncertain_extraction(case):
    proposed = move()
    batch = pending([proposed])
    if case == "locked":
        batch.before["actors"]["RIN"]["allowed_destinations"] = []
    elif case == "invalid":
        proposed["unknown_field"] = True
    elif case == "ambiguous":
        batch.proposals.append(move())
    else:
        proposed["basis"] = "uncertain"
    _, accepted, errors = _event(batch)
    assert errors and not accepted
    assert {entry.status for entry in batch.outcomes} == {
        "blocked" if case == "locked" else "unconfirmed"
    }


async def test_unconfirmed_shared_proposal_is_stamped_without_applying_a_movement():
    from unittest.mock import AsyncMock

    from backend.engine.narrated_items.runtime import KEY

    batch = pending([move()])
    reply = source("movement", batch.narration)
    host = SimpleNamespace(
        _pending_narrated_movement=batch,
        state=SimpleNamespace(entity_states={KEY: {}}),
        _save_chat_message=AsyncMock(),
    )
    complete(host, batch.proposals, confirmed=False)
    assert await finish(host, reply) == []
    saved = host.state.entity_states[KEY]["movement_check"]
    assert not saved["accepted"] and saved["outcomes"][0]["status"] == "unconfirmed"


def test_fallback_catchup_keeps_owner_qualification_after_current_audit_is_replaced():
    from backend.core.text_passages import Passage
    from backend.engine.narrated_items.runtime import KEY

    reply = source("fallback", TEXT)
    host = SimpleNamespace(
        state=SimpleNamespace(
            entity_states={KEY: {"movement_check": audit(reply, [outcome()])}},
            in_game_time=1,
        ),
    )
    turn = SimpleNamespace(
        fallback_identities={"npc": {}, "other": {}}, present_names={"npc": "Rin", "other": "Miki"}
    )
    recovery_queue.stamp(host, turn, reply)
    host.state.entity_states = {}  # Another turn replaced the one-turn diagnostics.
    batch = recovery_queue.Batch(
        message=reply,
        audit=recovery_queue.RecoveryAudit.model_validate(reply.npc_recovery),
        available={"h0": Passage(0, len(TEXT), TEXT)},
        offsets={"npc": 0, "other": 0},
    )
    recovery_perception.bind(
        batch,
        recovery_perception.RecoveryProjection(
            fragments={},
            history_fragments={"h0": {"kind": "public_event", "observers": ["npc", "other"]}},
        ),
    )
    assert not batch.error
    remembered = batch.accepted["npc"][0]
    assert remembered.text == TEXT and remembered.movement_outcomes == (outcome(),)
    assert remembered.action_span == remembered.history.evidence_span
    assert batch.accepted["other"][0].movement_outcomes == (outcome(),)


@pytest.mark.parametrize("status", ["applied", "blocked", "unconfirmed"])
async def test_completed_frame_does_not_reintroduce_unconfirmed_movement(status):
    from backend.engine.chpm import recent_scene
    from backend.engine.narrated_items.runtime import KEY
    from tests.conftest import TestSessionLocal
    from tests.test_chpm_observed_scene import ACTION, host, seed_frame

    async with TestSessionLocal() as db:
        _, state, reply = await seed_frame(db)
        state.entity_states = {
            **state.entity_states,
            KEY: {"movement_check": audit(reply, [outcome(status, text=ACTION, actor="LINA")])},
        }
        manager, _, _ = await host(db, state)
        views = await recent_scene.capture(manager, {"LINA"}, {"LINA", "__player__"})
        assert bool(views) is (status == "applied")
