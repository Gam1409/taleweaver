"""A narrated movement remains qualified through memory, recall and lifecycle boundaries."""

from types import SimpleNamespace

import pytest

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm import (
    agent_context,
    appraisal_context,
    host_sources,
    lifecycle,
    movement_feedback,
    passages,
    runtime,
)
from backend.engine.chpm.agent_limits import MAX_PINNED_CHARS
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind, Source, identifier, record
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import ActionEvidence, Verdict, validate_agent_evidence
from backend.engine.chpm.state import load, retract
from backend.engine.narrated_items.runtime import KEY as ITEMS
from backend.engine.narrated_movement.outcomes import MovementOutcome, evidence_size
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_chpm_memory import source
from tests.test_chpm_runtime import prepared

TEXT = "Rin walks through the door into the annex."


def outcome(status="blocked", *, text=TEXT, actor="npc", start=0):
    return MovementOutcome(
        actor_id=actor,
        status=status,
        evidence=text,
        evidence_span=EvidenceSpan(start=start, end=start + len(text)),
    )


def audit(reply, entries, **changes):
    return {
        "message_id": reply.id,
        "revision_id": reply.revision_id,
        "content_hash": digest(reply.content),
        "outcomes": [entry.model_dump(mode="json") for entry in entries],
        **changes,
    }


def delivered():
    host = prepared()
    reply = source("action", TEXT)
    host.state.entity_states[ITEMS] = {"movement_check": audit(reply, [outcome()])}
    host._chpm_turn.minds["npc"] = mind()
    host._chpm_turn.verdict = Verdict(
        matches=True, actions=[ActionEvidence(actor_id="npc", quote=TEXT)]
    )
    runtime.finish(host, reply, completed=True)
    return host, load(host.state), reply


def test_next_appraisal_and_tool_handoff_preserve_blocked_scope_and_exact_transcript():
    _, saved, _ = delivered()
    observer = saved.minds["npc"]
    key, remembered = next(iter(observer.sources.items()))
    assert remembered.text == TEXT and remembered.reported
    assert saved.memories["npc"][0].movement_outcomes == remembered.movement_outcomes
    window = appraisal_context.build(observer, current_message_id="next-input")
    visible = window.payload["visible_evidence"][0]
    assert visible["text"] == TEXT
    assert visible["movement_outcomes"][0]["status"] == "blocked"
    tools = Tools(observer, observation(message_id="next-input"), {})
    result = tools.expose(key, remembered, full=True)
    assert result["text"] == TEXT and result["movement_outcomes"] == visible["movement_outcomes"]
    chosen = saved.actors["npc"]
    chosen.agent_evidence = agent_context.collect(tools.pins, tools.observation)
    assert (
        agent_context.present(chosen, observer)[0]["movement_outcomes"]
        == result["movement_outcomes"]
    )
    chosen.agent_evidence[0].movement_outcomes = ()
    with pytest.raises(ChpmError, match="stale or differs"):
        agent_context.present(chosen, observer)


@pytest.mark.parametrize("change", ["message_id", "revision_id", "content_hash", "offset", "shape"])
def test_stale_or_invalid_owner_receipt_does_not_qualify_a_different_source(change):
    reply = source("action", TEXT)
    checked = audit(reply, [outcome()])
    if change == "offset":
        checked["outcomes"][0]["evidence_span"] = {"start": 1, "end": len(TEXT) + 1}
    elif change == "shape":
        checked["outcomes"] = [{"status": "blocked"}]
    else:
        checked[change] = "stale"
    state = SimpleNamespace(entity_states={ITEMS: {"movement_check": checked}})
    assert movement_feedback.read(state, reply) == ()


def test_source_qualification_round_trips_forks_and_retracts_with_its_transcript():
    host, saved, reply = delivered()
    observer = saved.minds["npc"]
    assert Mind.model_validate_json(observer.model_dump_json()) == observer
    assert host_sources.from_messages(observer, {reply.id: reply}) == observer
    forked = lifecycle.fork(host.state.entity_states, {reply.id: "copied-action"}, "fork")
    copied = load(SimpleNamespace(entity_states=forked)).minds["npc"]
    remembered = next(iter(copied.sources.values()))
    assert remembered.message_id == "copied-action" and remembered.movement_outcomes == (outcome(),)
    assert (
        copied.genesis.scope.world_id == "fork"
        and not load(SimpleNamespace(entity_states=forked)).actors
    )
    reply.content += " Edited."
    assert not host_sources.from_messages(observer, {reply.id: reply}).sources
    retract(host.state, reply.id)
    assert not load(host.state).minds["npc"].sources


def test_legacy_source_shape_and_identifier_are_unchanged_without_receipts():
    remembered = Source(
        message_id="old",
        content_hash="old-hash",
        role="assistant",
        speaker_id="npc",
        kind="narration",
        text=TEXT,
    )
    raw = remembered.model_dump()
    assert "movement_outcomes" not in raw
    legacy_body = {
        "message_id": "old",
        "revision_id": None,
        "content_hash": "old-hash",
        "role": "assistant",
        "speaker_id": "npc",
        "kind": "narration",
        "text": TEXT,
    }
    # Fixed pre-change serialized shape, rather than comparing two current serializers.
    from backend.engine.chpm.host_state import fingerprint

    assert raw == {**legacy_body, "facts": None, "graph": None}
    assert identifier(remembered, mind().genesis) == fingerprint(
        {
            "scope": {"world_id": "session", "branch_id": "session-main-v1", "observer_id": "npc"},
            "source": legacy_body,
        }
    )


def test_qualified_text_is_charged_to_the_same_tool_and_handoff_budget():
    remembered = Source(
        message_id="action",
        content_hash="hash",
        role="assistant",
        speaker_id="npc",
        kind="narration",
        text=TEXT,
        movement_outcomes=(outcome(),),
    )
    observer = record(mind(), remembered, minute=1)
    key = identifier(remembered, observer.genesis)
    tools = Tools(observer, observation(), {})
    other = remembered.model_copy(update={"text": "x" * 2000, "movement_outcomes": ()})
    reserve = evidence_size(TEXT, remembered) - len(TEXT)
    for index, length in enumerate([2000, 2000, MAX_PINNED_CHARS - 4000 - len(TEXT) - reserve]):
        tools.pins[f"p{index}"] = (f"other-{index}", other, "x" * length)
    assert tools.expose(key, remembered, full=True)["status"] == "ok"
    pinned = agent_context.collect(tools.pins, observation())
    validate_agent_evidence(pinned)
    alias = next(alias for alias, item in tools.pins.items() if item[0] == key)
    tools.pins["p0"] = ("other-0", other, "x" * 2001)
    assert tools.expose(key, remembered, full=True)["status"] == "evidence_budget_exhausted"
    assert tools.pins[alias][2] == TEXT


@pytest.mark.parametrize("occurrence", [0, 1])
def test_repeated_reviewed_words_keep_the_selected_occurrence(occurrence):
    host = prepared()
    reply = source("repeated", TEXT + "\n" + TEXT)
    host._chpm_turn.minds["npc"] = mind()
    host.state.entity_states[ITEMS] = {"movement_check": audit(reply, [outcome()])}
    host._chpm_turn.verdict = passages.resolve(
        passages.Review(
            matches=True, actions=[{"actor_id": "npc", "passage_id": f"p{occurrence}"}]
        ),
        passages.index(reply.content),
        text=reply.content,
    )
    runtime.finish(host, reply, completed=True)
    saved = load(host.state)
    remembered = next(iter(saved.minds["npc"].sources.values()))
    assert remembered.action_span.start == occurrence * (len(TEXT) + 1)
    assert remembered.movement_outcomes == ((outcome(),) if occurrence == 0 else ())


def test_movement_receipt_spanning_two_sentences_qualifies_the_reviewed_part():
    host = prepared()
    whole = TEXT + " Rin leaves the waiting room behind."
    reply = source("wide-receipt", whole)
    host._chpm_turn.minds["npc"] = mind()
    host.state.entity_states[ITEMS] = {"movement_check": audit(reply, [outcome(text=whole)])}
    host._chpm_turn.verdict = passages.resolve(
        passages.Review(matches=True, actions=[{"actor_id": "npc", "passage_id": "p0"}]),
        passages.index(whole),
        text=whole,
    )
    runtime.finish(host, reply, completed=True)
    remembered = next(iter(load(host.state).minds["npc"].sources.values()))
    # The public reviewed source does not inherit adjacent, potentially private text.
    assert remembered.text == TEXT and remembered.movement_outcomes == (outcome(),)
    assert host_sources.from_messages(load(host.state).minds["npc"], {reply.id: reply}).sources


def test_semantic_hits_cannot_overfill_the_qualified_evidence_handoff():
    from backend.engine.chpm import semantic_recall
    from backend.engine.chpm.schema import EpisodeContext

    _, saved, _ = delivered()
    observer = saved.minds["npc"]
    key, remembered = next(iter(observer.sources.items()))
    plain = remembered.model_copy(
        update={"text": "x" * 2000, "movement_outcomes": (), "action_span": None}
    )
    pins = {
        f"a{i}": (f"plain-{i}", plain, "x" * size)
        for i, size in enumerate((2000, 2000, MAX_PINNED_CHARS - 4000 - len(TEXT)))
    }
    hits = [semantic_recall.Hit(key, TEXT, EpisodeContext(scene_id="room", evidence_order=0), 1.0)]
    merged = semantic_recall.merge(observer, pins, hits)
    assert merged == pins
    validate_agent_evidence(agent_context.collect(merged, observation()))
