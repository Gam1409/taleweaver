from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.text_passages import spans
from backend.engine import prose_evidence as evidence

ACTORS = {"__player__": "Hero", "RIN": "Rin"}


def event(quote, *, kind="custody", value="placed", passage="p0", **attributes):
    return {
        "event": quote,
        "event_attributes": {
            "kind": kind,
            "passage_id": passage,
            "performer_id": "__player__",
            "actor_id": "__player__",
            "value": value,
            **attributes,
        },
    }


def review(text, entries, items=None):
    return evidence.grounded(
        evidence.Proposals(extractions=entries), spans(text), ACTORS, items or {}
    )


def test_literal_unicode_offsets_and_item_binding_do_not_guess_container():
    text = "Свет погас. Рин подняла лист из журнала."
    quote = "подняла лист"
    rows, discarded = review(
        text, [event(quote, passage="p1", item_mention="журнал")], {"BOOK": "журнал"}
    )
    assert discarded == 0
    (row,) = rows
    assert text[row["start"] : row["end"]] == quote
    assert row["item_id"] is None and not row["resolved"]
    assert not row["latest"]


def test_duplicate_names_and_unknown_receivers_remain_unresolved():
    text = "I give the coat to her."
    entry = event(text, value="given", item_mention="coat", recipient_id="MISSING")
    (row,) = review(text, [entry], {"ONE": "coat", "TWO": "Coat"})[0]
    assert (row["item_id"], row["recipient_id"], row["resolved"]) == (None, None, False)
    (row,) = review(text, [entry], {"COAT": "Coat"})[0]
    assert (row["item_id"], row["resolved"]) == ("COAT", False)


def test_alignment_discards_fabrication_ambiguous_occurrences_and_unknown_enums():
    text = "Coat, coat, coat."
    candidates = [
        event("coat"),
        event("a glove"),
        event("Coat", passage="p9"),
        event("Coat", kind="posture", value="walked away"),
    ]
    assert review(text, candidates) == ([], 4)


def test_last_unambiguous_source_event_survives_reversal_in_model_output_order():
    text = "I remove my coat. I put the coat on."
    entries = [
        event(
            "I put the coat on", passage="p1", kind="clothing", value="worn", item_mention="coat"
        ),
        event("I remove my coat", kind="clothing", value="removed", item_mention="coat"),
    ]
    rows, discarded = review(text, entries, {"C": "coat"})
    assert discarded == 0
    assert [(r["value"], r["latest"]) for r in rows] == [("removed", False), ("worn", True)]


def test_duplicate_proposals_preserve_separate_occurrences_and_concurrent_facts():
    text = "I kneel. I stand. I kneel."
    kneel = event("I kneel", kind="posture", value="kneeling")
    feeling = event("I kneel", kind="emotion", value="relief")
    stand = event("I stand", passage="p1", kind="posture", value="standing")
    again = event("I kneel", passage="p2", kind="posture", value="kneeling")
    rows, discarded = review(text, [kneel, feeling, stand, kneel, again, again])
    assert discarded == 0
    assert [(row["value"], row["start"], row["latest"]) for row in rows] == [
        ("kneeling", 0, False),
        ("relief", 0, False),
        ("standing", 9, False),
        ("kneeling", 18, True),
    ]


def test_same_quote_preserves_distinct_items_recipients_and_unresolved_mentions():
    text = "I offer the scarf, cap, pin and ring to Rin."

    def give(name, actor):
        return event(text, value="given", item_mention=name, recipient_id=actor)

    rows, discarded = review(
        text,
        [
            give("scarf", "RIN"),
            give("SCARF", "RIN"),
            give("scarf", "__player__"),
            give("cap", "RIN"),
            give("pin", "RIN"),
            give("ring", "RIN"),
            event("invented quote"),
        ],
        {"SCARF": "scarf", "CAP": "cap"},
    )
    assert discarded == 1
    assert [(row["item_id"], row["recipient_id"]) for row in rows] == [
        ("SCARF", "RIN"),
        ("SCARF", "__player__"),
        ("CAP", "RIN"),
        (None, "RIN"),
        (None, "RIN"),
    ]


@pytest.mark.asyncio
async def test_independent_reads_merge_grounded_events_in_source_order():
    text = "I remove my coat. I kneel and put the coat on."
    removed = event("remove my coat", kind="clothing", value="removed", item_mention="coat")
    worn = event(
        "kneel and put the coat on",
        passage="p1",
        kind="clothing",
        value="worn",
        item_mention="coat",
    )
    shorter = event(
        "put the coat on", passage="p1", kind="clothing", value="worn", item_mention="coat"
    )
    pose = event("kneel", passage="p1", kind="posture", value="kneeling")
    conflict = event(
        "put the coat on", passage="p1", kind="clothing", value="removed", item_mention="coat"
    )
    llm = SimpleNamespace(
        model="local",
        aexecute_complex_task=AsyncMock(
            side_effect=[
                {"extractions": [worn]},
                {"extractions": [removed, shorter, pose]},
                {"extractions": [conflict]},
            ]
        ),
    )
    message = {"role": "user", "content": text, "id": "m", "revision_id": "r"}
    result = await evidence.review(llm, "session", message, ACTORS, {"C": "coat"}, passes=3)
    assert [(r["value"], r["latest"]) for r in result["events"]] == [
        ("removed", False),
        ("kneeling", True),
        ("worn", True),
    ]
    assert result["completed_passes"] == result["requested_passes"] == 3
    assert result["discarded"] == 1
    calls = llm.aexecute_complex_task.await_args_list
    assert len({c.args[1] for c in calls}) == 1
    assert [c.kwargs["metadata"]["extraction_pass"] for c in calls] == [1, 2, 3]
    assert all(c.kwargs["single_attempt"] for c in calls)


@pytest.mark.asyncio
async def test_failed_supplemental_debug_read_preserves_partial_results():
    llm = SimpleNamespace(
        model="local",
        aexecute_complex_task=AsyncMock(
            side_effect=[
                {"extractions": [event("kneel", kind="posture", value="kneeling")]},
                TimeoutError(),
            ]
        ),
    )
    message = {"role": "user", "content": "I kneel.", "id": "m", "revision_id": "r"}
    result = await evidence.review(llm, "session", message, ACTORS, {}, passes=3)
    assert result["completed_passes"] == 1 and result["requested_passes"] == 3
    assert [r["quote"] for r in result["events"]] == ["kneel"]
    assert llm.aexecute_complex_task.await_count == 2
