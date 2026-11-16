"""Older relevant own events compete without exposing another actor's journal."""

import json

from backend.engine.living_world import event_recall
from backend.engine.living_world.schema import Event, Simulation


def test_old_own_commitment_survives_recent_window_and_all_bounds():
    events = [
        Event(
            event_id="promise",
            due=1,
            kind="SOCIAL",
            actor="A",
            participant="B",
            status="COMMITTED",
            result='A said to B: "I will return the silver treaty."',
            committed_at=1,
        ),
        Event(
            event_id="followup",
            due=2,
            kind="MEET",
            actor="B",
            participant="A",
            status="COMMITTED",
            result="A and B discussed the treaty.",
            dependencies=["promise"],
        ),
        *[
            Event(
                event_id=f"routine-{i}",
                due=i + 3,
                kind="MOVE",
                actor="A",
                status="COMMITTED",
                result="A moved along the corridor.",
            )
            for i in range(8)
        ],
        Event(
            event_id="private",
            due=11,
            kind="SOCIAL",
            actor="B",
            participant="C",
            status="COMMITTED",
            result="Private silver treaty conversation.",
        ),
        Event(
            event_id="deferred",
            due=12,
            kind="MOVE",
            actor="A",
            status="DEFERRED",
            result="silver treaty",
        ),
        Event(
            event_id="rejected",
            due=13,
            kind="MOVE",
            actor="A",
            status="CANCELLED",
            result="silver treaty",
        ),
        Event(
            event_id="future",
            due=50,
            kind="SOCIAL",
            actor="A",
            status="COMMITTED",
            result="silver treaty",
        ),
    ]
    simulation = Simulation(events=events, cursor=20, target=60)
    decision = Event(event_id="choice", due=20, kind="DECISION", actor="A")
    context = {
        "actor": {"authored_goal": "Return the silver treaty"},
        "private_notes": {},
        "scene": {"description": "A corridor"},
        "participants": [],
        "observations": [item.result for item in event_recall.eligible(simulation, decision)][-8:],
    }
    result = event_recall.recall(simulation, decision, context)
    assert {item["event_id"] for item in result} == {"promise", "followup"}
    assert (
        "unverified"
        in next(item for item in result if item["event_id"] == "promise")["epistemic_status"]
    )
    assert next(item for item in result if item["event_id"] == "followup")["requires"] == [
        "promise"
    ]
    assert all("treaty" not in text for text in context["observations"])
    assert len(result) <= event_recall.MAX_RECALLED_EVENTS
    assert len(json.dumps(result, ensure_ascii=False)) <= event_recall.MAX_RECALLED_CHARS
    assert simulation.events == events


def test_full_journal_recall_stays_bounded_and_does_not_repeat_recent_events():
    events = [
        Event(
            event_id=f"event-{i}",
            due=i,
            kind="SOCIAL",
            actor="A",
            participant="B",
            status="COMMITTED",
            result="The silver treaty " + "x" * 270,
        )
        for i in range(512)
    ]
    simulation = Simulation(events=events, cursor=512, target=512)
    decision = Event(event_id="choice", due=512, kind="DECISION", actor="A")
    context = {
        "actor": {"authored_goal": "silver treaty"},
        "private_notes": {},
        "scene": {"description": ""},
        "participants": [],
        "observations": [item.result for item in events[-8:]],
    }
    result = event_recall.recall(simulation, decision, context)
    identifiers = [item["event_id"] for item in result]
    assert result and len(identifiers) == len(set(identifiers)) <= 3
    assert not set(identifiers) & {item.event_id for item in events[-8:]}
    assert len(json.dumps(result, ensure_ascii=False)) <= 1200
    assert len(simulation.events) == 512
