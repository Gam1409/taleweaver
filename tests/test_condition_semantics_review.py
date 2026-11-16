"""Physical facts retain the final source occurrence across shared extraction."""

from typing import Any

import pytest

from backend.engine.narrated_items.evidence import Catalog, bind
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.physical_conditions.ledger import apply, read

INITIAL = "The traveler's left hand is trembling."
EARLIER = "The traveler's left hand is trembling slightly."
LATER = "By the end, the traveler's left hand is trembling strongly."


def _apply(
    states: dict,
    proposals: list[Any],
    narration: str,
    message: str,
    *,
    manual: bool = False,
) -> tuple[dict, list[str], list[str]]:
    return apply(
        states,
        proposals,
        targets={"TRAVELER", "FLASK"},
        item_targets={"FLASK"},
        narration=narration,
        message_id=message,
        session_id="condition-semantics-test",
        minute=5,
        manual=manual,
    )


def _record(quote: str, kind: str = "other", part: str = "left hand") -> dict[str, Any]:
    return {
        "operation": "record",
        "target_id": "FLASK" if kind == "item_state" else "TRAVELER",
        "kind": kind,
        "part": "temperature" if kind == "item_state" else part,
        "detail": quote,
        "evidence": quote,
    }


def _initial(kind: str = "other") -> tuple[dict, str]:
    quote = "The flask is warm." if kind == "item_state" else INITIAL
    states, identifiers, errors = _apply({}, [_record(quote, kind)], quote, "initial-reply")
    assert not errors and len(identifiers) == 1
    return states, identifiers[0]


def _change(identifier: str, quote: str, operation: str = "change") -> dict[str, Any]:
    return {
        "operation": operation,
        "condition_id": identifier,
        "detail": quote,
        "evidence": quote,
    }


def _bound(narration: str, proposals: list[Any]) -> list[Any]:
    catalog = Catalog(narration, scope="condition-source-order")
    bound = bind(SharedItemExtraction(condition_updates=proposals), narration, catalog=catalog)
    return list(bound.condition_updates)


@pytest.mark.parametrize("bound", [False, True])
def test_reverse_source_order_cannot_replace_a_later_bodily_fact_with_an_earlier_one(
    bound: bool,
) -> None:
    states, identifier = _initial()
    narration = EARLIER + " " + LATER
    proposals = [_change(identifier, LATER), _change(identifier, EARLIER)]
    if bound:
        proposals = _bound(narration, proposals)

    result, accepted, errors = _apply(states, proposals, narration, "changed-reply")

    condition = read(result).conditions[identifier]
    assert accepted == [identifier] and len(errors) == 1 and "order" in errors[0]
    assert condition.detail == condition.latest.quote == LATER
    assert len(read(result).events) == 2
    if bound:
        assert condition.latest.evidence_span
        assert condition.latest.evidence_span.start == len(EARLIER) + 1


@pytest.mark.parametrize("kind", ["other", "item_state"])
def test_ascending_changes_keep_the_same_condition_and_later_exact_source(kind: str) -> None:
    states, identifier = _initial(kind)
    earlier, later = (
        ("The flask is warm.", "The flask is cold.") if kind == "item_state" else (EARLIER, LATER)
    )
    narration = earlier + " " + later
    proposals = _bound(narration, [_change(identifier, earlier), _change(identifier, later)])

    result, accepted, errors = _apply(states, proposals, narration, "changed-reply")

    assert not errors and accepted == [identifier, identifier]
    condition = read(result).conditions[identifier]
    assert condition.detail == condition.latest.quote == later
    assert condition.origin == read(states).conditions[identifier].origin


@pytest.mark.parametrize("same_span", [False, True])
def test_overlapping_sources_cannot_authorize_a_second_change(same_span: bool) -> None:
    states, identifier = _initial()
    overlapping = EARLIER if same_span else "left hand is trembling"
    start = EARLIER.index(overlapping)
    proposals = [
        {**_change(identifier, EARLIER), "evidence_span": {"start": 0, "end": len(EARLIER)}},
        {
            **_change(identifier, overlapping),
            "evidence_span": {"start": start, "end": start + len(overlapping)},
        },
    ]

    result, accepted, errors = _apply(states, proposals, EARLIER, "changed-reply")

    assert accepted == [identifier] and len(errors) == 1 and "order" in errors[0]
    assert read(result).conditions[identifier].latest.quote == EARLIER


@pytest.mark.parametrize("kind", ["other", "item_state"])
@pytest.mark.parametrize("repeat_previous", [False, True])
def test_legacy_ambiguous_occurrences_preserve_the_latest_accepted_fact(
    kind: str, repeat_previous: bool
) -> None:
    states, identifier = _initial(kind)
    earlier, later = (
        ("The flask is warm.", "The flask is cold.") if kind == "item_state" else (EARLIER, LATER)
    )
    narration = " ".join([earlier, earlier, later] if repeat_previous else [earlier, later, later])

    result, accepted, errors = _apply(
        states,
        [_change(identifier, earlier), _change(identifier, later)],
        narration,
        "changed-reply",
    )

    assert accepted == [identifier] and len(errors) == 1 and "order" in errors[0]
    assert read(result).conditions[identifier].latest.quote == earlier


@pytest.mark.parametrize("kind", ["other", "item_state"])
def test_overlapping_literal_occurrences_are_ambiguous_without_offsets(kind: str) -> None:
    states, identifier = _initial(kind)
    earlier, later = (
        ("warm warm", "The flask is cool.")
        if kind == "item_state"
        else ("pale pale", "The skin is clear.")
    )
    narration = (
        "The flask is warm warm warm. " if kind == "item_state" else "The skin is pale pale pale. "
    ) + later

    result, accepted, errors = _apply(
        states,
        [_change(identifier, earlier), _change(identifier, later)],
        narration,
        "changed-reply",
    )

    assert accepted == [identifier] and len(errors) == 1 and "order" in errors[0]
    assert read(result).conditions[identifier].latest.quote == earlier


def test_selected_repeated_occurrences_keep_exact_unicode_character_offsets() -> None:
    states, identifier = _initial()
    narration = "☕ A café clock chimes. " + " ".join([EARLIER, LATER, EARLIER])
    catalog = Catalog(narration, scope="condition-unicode-order")
    references = list(catalog.narration_passages)[1:]
    proposals = [
        {**_change(identifier, quote), "evidence": reference}
        for quote, reference in zip([EARLIER, LATER, EARLIER], references, strict=True)
    ]
    bound = bind(SharedItemExtraction(condition_updates=proposals), narration, catalog=catalog)

    result, accepted, errors = _apply(states, bound.condition_updates, narration, "changed-reply")

    assert not errors and accepted == [identifier] * 3
    source = read(result).conditions[identifier].latest
    assert source.quote == EARLIER and source.evidence_span
    assert source.evidence_span.start == narration.rindex(EARLIER)
    assert source.evidence_span.matches(narration, EARLIER)
    assert len(narration[: source.evidence_span.start].encode()) > source.evidence_span.start


def test_previous_message_offsets_do_not_restrict_a_new_message() -> None:
    previous = "The long hallway is quiet. " * 8 + INITIAL
    proposals = _bound(previous, [_record(INITIAL)])
    states, identifiers, errors = _apply({}, proposals, previous, "initial-reply")
    assert not errors
    old_source = read(states).conditions[identifiers[0]].latest
    assert old_source.evidence_span and old_source.evidence_span.start > len(LATER)

    result, accepted, errors = _apply(
        states,
        _bound(LATER, [_change(identifiers[0], LATER)]),
        LATER,
        "changed-reply",
    )

    assert not errors and accepted == identifiers
    condition = read(result).conditions[identifiers[0]]
    assert condition.latest.quote == LATER and condition.latest.message_id == "changed-reply"


def test_invalid_exact_offset_still_preserves_the_previous_condition() -> None:
    states, identifier = _initial()
    narration = "☕ A café clock chimes. " + LATER
    proposal = _bound(narration, [_change(identifier, LATER)])[0]
    proposal["evidence_span"]["start"] += 1

    result, accepted, errors = _apply(states, [proposal], narration, "changed-reply")

    assert not accepted and errors and "original source occurrence" in errors[0]
    assert read(result).conditions == read(states).conditions
    assert read(result).events == read(states).events


@pytest.mark.parametrize(
    "kind,operations,quotes",
    [
        (
            "contamination",
            ["reduce", "remove"],
            ["Only a faint blue ink stain remains.", "The blue ink stain is completely gone."],
        ),
        (
            "injury",
            ["treat", "heal"],
            ["The shallow hand cut is bandaged.", "The shallow hand cut has healed completely."],
        ),
    ],
)
def test_source_order_preserves_partial_and_resolution_operations(
    kind: str, operations: list[str], quotes: list[str]
) -> None:
    initial = "A shallow hand cut remains." if kind == "injury" else "A blue ink stain remains."
    states, identifiers, errors = _apply({}, [_record(initial, kind)], initial, "initial-reply")
    assert not errors
    narration = " ".join(quotes)
    proposals = [
        _change(identifiers[0], quote, operation)
        for quote, operation in zip(quotes, operations, strict=True)
    ]

    result, accepted, errors = _apply(
        states, _bound(narration, proposals), narration, "changed-reply"
    )

    assert not errors and accepted == identifiers * 2
    condition = read(result).conditions[identifiers[0]]
    assert condition.status == "resolved" and condition.latest.quote == quotes[-1]
    assert [event.operation for event in read(result).events] == ["record", *operations]


def test_order_rejection_preserves_an_independent_condition_on_the_same_actor() -> None:
    states, identifier = _initial()
    independent = "A blue ink spot remains on the traveler's cheek."
    narration = " ".join([EARLIER, LATER, independent])
    proposals = [
        _change(identifier, LATER),
        _change(identifier, EARLIER),
        _record(independent, "contamination", "cheek"),
    ]

    result, accepted, errors = _apply(
        states, _bound(narration, proposals), narration, "changed-reply"
    )

    assert len(accepted) == 2 and len(errors) == 1
    conditions = read(result).conditions
    assert conditions[identifier].latest.quote == LATER
    assert conditions[accepted[1]].detail == independent


def test_manual_corrections_keep_their_requested_operation_order() -> None:
    states, identifier = _initial()
    narration = EARLIER + " " + LATER

    result, accepted, errors = _apply(
        states,
        [_change(identifier, LATER), _change(identifier, EARLIER)],
        narration,
        "manual-correction",
        manual=True,
    )

    assert not errors and accepted == [identifier, identifier]
    condition = read(result).conditions[identifier]
    assert condition.detail == EARLIER and condition.latest.kind == "manual"
