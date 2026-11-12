"""Mutable item facts preserve canonical identity and explicit partial/negative states."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.physical_conditions.item_state import project
from backend.engine.physical_conditions.ledger import apply, read, remap
from backend.engine.physical_conditions.presentation import narration_block
from backend.engine.physical_conditions.references import bind_records
from backend.engine.physical_conditions.schema import KEY


def record(detail="The flask is half full.", part="fill_level", target="flask", **kw):
    return dict(
        operation="record",
        target_id=target,
        kind="item_state",
        part=part,
        detail=detail,
        evidence=detail,
        visibility="public",
        **kw,
    )


def update(states, proposals, message="m1", minute=5, narration=None, **kw):
    return apply(
        states,
        proposals,
        targets={"flask", "paper", "matches", "__player__"},
        item_targets={"flask", "paper", "matches"},
        narration=narration or " ".join(p["evidence"] for p in proposals),
        message_id=message,
        session_id="session",
        minute=minute,
        **kw,
    )


@pytest.mark.parametrize(
    "part,values",
    [
        ("contents", ["The flask is full.", "The flask is half full.", "The flask is empty."]),
        ("cleanliness", ["The flask is clean.", "The flask is dirty.", "The flask is clean."]),
        ("form", ["The paper is smooth.", "The paper is crumpled.", "The paper is smooth."]),
        ("inscription", ["The paper is blank.", "The paper says HELLO.", "The paper is blank."]),
        ("supply", ["Three matches remain.", "A few matches remain.", "No matches remain."]),
    ],
)
def test_changes_omission_repeat_and_history(part, values):
    states = {}
    identifier = None
    for index, detail in enumerate(values):
        states, accepted, errors = update(states, [record(detail, part)], f"m{index}", index * 5)
        assert not errors
        identifier = identifier or accepted[0]
        assert accepted == [identifier]
    ledger = read(states)
    row = ledger.conditions[identifier]
    assert row.detail == values[-1] and row.status == "active"
    assert row.first_recorded_minute == 0 and row.last_changed_minute == 10
    assert [event.detail for event in ledger.events] == values
    assert [event.minute for event in ledger.events] == [0, 5, 10]
    same, _, errors = update(states, [record(values[-1], part)], "repeat", 30)
    assert not errors and read(same).conditions[identifier].last_changed_minute == 10
    unchanged, _, _ = update(same, [], "omitted", 60)
    assert read(unchanged).conditions == read(same).conditions
    assert read(deepcopy(unchanged)) == read(unchanged)


def test_independent_dimensions_and_readonly_private_projection():
    item = dict(
        id="flask", name="Flask", description="An empty smooth flask.", image_url="/old.png"
    )
    before = deepcopy(item)
    states, _, errors = update({}, [record(), record("The flask is dirty.", "cleanliness")])
    assert not errors
    view = project([item], states)[0]
    assert item == before and view["description"] == before["description"]
    assert view["image_url"] == before["image_url"] and len(view["current_state"]) == 2
    assert {r["part"] for r in states[KEY]["conditions"].values()} == {"fill_level", "cleanliness"}
    hidden = deepcopy(states)
    for row in hidden[KEY]["conditions"].values():
        row["visibility"] = "private"
    assert "current_state" not in project([view], hidden)[0]
    assert len(project([item], hidden, private=True)[0]["current_state"]) == 2
    assert "current_state" not in project([view], {})[0]  # No stale copied projection.


def test_ordered_changes_repeated_wording_and_out_of_order_rejection():
    first, last = "The flask is full.", "The flask is empty."
    states, ids, errors = update({}, [record(first), record(last)])
    assert not errors and len(set(ids)) == 1
    assert next(iter(read(states).conditions.values())).detail == last
    _, _, errors = update({}, [record(last), record(first)], narration=first + " " + last)
    assert errors and "order" in errors[0]
    text = first + " " + last + " " + first
    proposals = [record(first), record(last), record(first)]
    offsets = [
        (0, len(first)),
        (len(first) + 1, len(first) + 1 + len(last)),
        (len(text) - len(first), len(text)),
    ]
    for proposal, (start, end) in zip(proposals, offsets, strict=True):
        proposal["evidence_span"] = {"start": start, "end": end}
    states, ids, errors = update({}, proposals, narration=text)
    assert not errors and len(set(ids)) == 1
    assert next(iter(read(states).conditions.values())).detail == first


def test_player_report_needs_both_saved_report_and_completed_confirmation():
    proposal = record("The flask is half full.", player_evidence="The flask is half full.")
    proposal["evidence"] = "You check it and confirm that."
    states, _, errors = update({}, [proposal], player_message=("user-1", proposal["detail"]))
    assert not errors
    row = next(iter(read(states).conditions.values()))
    assert row.reported_by.kind == "player" and row.reported_by.message_id == "user-1"
    assert row.latest.message_id == "m1"
    copied = read(remap(states, {"user-1": "copy-user", "m1": "copy-reply"}))
    assert copied.conditions[row.id].reported_by.message_id == "copy-user"
    assert copied.events[0].reported_by.message_id == "copy-user"
    for kwargs in (
        {},
        {"player_message": ("other", "Different text.")},
        {"player_message": ("user-1", proposal["detail"]), "narration": "Nothing happened."},
    ):
        rejected, accepted, errors = update({}, [proposal], **kwargs)
        assert errors and not accepted and not read(rejected).conditions


def test_invalid_amount_actor_and_removal_leave_known_state():
    states, ids, _ = update({}, [record()])
    for proposal in [
        record(target="__player__"),
        record(part="Invalid Property"),
        {**record("Three units remain."), "evidence": "Some water remains."},
        dict(operation="remove", condition_id=ids[0], evidence="The flask is empty."),
    ]:
        result, accepted, errors = update(states, [proposal], "bad")
        assert errors and not accepted and read(result).conditions == read(states).conditions


def test_next_prompt_and_reference_binding_keep_current_fact():
    states, ids, _ = update({}, [record()])
    bound, _ = bind_records(read(states), [record("The flask is empty.")])
    assert bound[0]["condition_id"] == ids[0]
    states, _, errors = update(states, bound, "m2")
    assert not errors
    block = narration_block(
        SimpleNamespace(entity_states=states), {}, detailed=False, visible_item_ids={"flask"}
    )
    assert "The flask is empty." in block and "half full" not in block
    assert "supersede" in block
