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
