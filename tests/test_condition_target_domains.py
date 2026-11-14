"""New bodily signs cannot masquerade as a known item's placement update."""

import pytest

from backend.engine.physical_conditions.ledger import apply, read


def run(proposals, *, states=None, reply="reply", manual=False):
    narration = " ".join(proposal["evidence"] for proposal in proposals) or "Nothing changes."
    return apply(
        states or {},
        proposals,
        targets={"NPC", "COAT"},
        item_targets={"COAT"},
        narration=narration,
        message_id=reply,
        session_id="session",
        minute=10,
        manual=manual,
    )


def record(**changes):
    return {
        "operation": "record",
        "target_id": "COAT",
        "kind": "injury",
        "part": "sleeves",
        "detail": "Sleeves pushed above the elbows.",
        "evidence": "She pulls the coat sleeves above both elbows and keeps the coat on.",
        **changes,
    }


@pytest.mark.parametrize("kind", ["injury", "pain"])
def test_new_item_records_cannot_borrow_a_bodily_condition_domain(kind):
    changed, accepted, errors = run([record(kind=kind)])
    assert not accepted and errors
    assert not read(changed).conditions
    assert "item" in errors[0].lower()


def test_a_rejected_garment_condition_does_not_discard_an_independent_body_sign():
    changed, accepted, errors = run(
        [
            record(),
            record(
                target_id="NPC",
                kind="other",
                part="hands",
                detail="Hands tremble.",
                evidence="Her hands continue trembling.",
            ),
        ]
    )
    assert len(accepted) == 1 and len(errors) == 1
    saved = read(changed).conditions[accepted[0]]
    assert saved.target_id == "NPC" and saved.kind == "other"


@pytest.mark.parametrize("kind", ["contamination", "fluid"])
def test_known_items_still_accept_explicit_surface_traces(kind):
    changed, accepted, errors = run([record(kind=kind, part="surface", detail="A visible trace.")])
    assert len(accepted) == 1 and not errors
    assert read(changed).conditions[accepted[0]].kind == kind


@pytest.mark.parametrize(
    ("part", "detail"), [("form", "creased"), ("cleanliness", "clean"), ("damage", "torn")]
)
def test_generic_item_properties_keep_their_existing_extensible_contract(part, detail):
    changed, accepted, errors = run(
        [
            record(
                kind="item_state",
                part=part,
                detail=detail,
                evidence=f"The coat is {detail}.",
            )
        ]
    )
    assert len(accepted) == 1 and not errors
    saved = read(changed).conditions[accepted[0]]
    assert saved.target_id == "COAT" and saved.part == part and saved.detail == detail


def test_existing_and_manual_records_are_retained_and_can_still_be_updated():
    initial, accepted, errors = run([record()], manual=True)
    assert len(accepted) == 1 and not errors
    identifier = accepted[0]
    unchanged, _, errors = run([], states=initial, reply="later")
    assert (
        not errors
        and read(unchanged).conditions[identifier] == read(initial).conditions[identifier]
    )
    changed, updated, errors = run(
        [
            {
                "operation": "change",
                "condition_id": identifier,
                "detail": "An established legacy detail is refreshed.",
                "evidence": "The established sleeve detail is unchanged.",
            }
        ],
        states=unchanged,
        reply="refresh",
    )
    assert updated == [identifier] and not errors
    assert read(changed).conditions[identifier].target_id == "COAT"


def test_existing_other_item_damage_remains_a_valid_physical_fact():
    changed, accepted, errors = run(
        [
            record(
                kind="other",
                part="left seam",
                detail="A small torn hole.",
                evidence="A nail tore a small hole in the left seam.",
            )
        ]
    )
    assert len(accepted) == 1 and not errors
    assert read(changed).conditions[accepted[0]].kind == "other"


def test_a_known_item_id_is_not_treated_as_a_body_even_if_the_union_contains_it():
    # The subject union alone cannot decide ownership; the item allowlist is authoritative.
    changed, accepted, errors = run([record(part="hands")])
    assert not accepted and errors and not read(changed).conditions
