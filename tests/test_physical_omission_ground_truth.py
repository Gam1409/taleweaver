"""A complete response can still omit or misinterpret an event; gold cases expose both."""

import pytest

from backend.engine.narrated_items.evidence import Catalog, bind
from backend.engine.narrated_items.response_sections import read as sections
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.physical_conditions.ledger import apply
from backend.engine.physical_conditions.schema import KEY
from tests.physical_omission_cases import CASES, initial, score
from tests.state_response_fixture import extraction
from tests.test_physical_conditions import TARGETS


def run(case, *, omit=False, wrong=False):
    states, ids = initial()
    catalog = Catalog(case.text, scope=case.id)
    proposals = []
    if case.target and not omit:
        ref = next(
            key
            for key, text in catalog.narration_passages.items()
            if text == case.evidence
            and catalog.resolve(key, allow_room=False).span.start == case.start
        )
        proposals = [
            {"operation": case.operation, "condition_id": ids[case.target], "evidence": ref}
        ]
    elif wrong:
        proposals = [
            {
                "operation": "treat",
                "condition_id": ids["neck"],
                "evidence": next(iter(catalog.narration_passages)),
            }
        ]
    packet = extraction(SharedItemExtraction, condition_updates=proposals)
    assert not sections(packet, staging=False).unconfirmed
    bound = bind(packet, case.text, catalog=catalog)
    changed, _, errors = apply(
        states,
        bound.condition_updates,
        targets=TARGETS,
        narration=case.text,
        message_id="current",
        session_id="session",
        minute=1,
    )
    assert not errors
    return changed, ids


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_expected_event_or_unchanged_control_has_the_correct_target_and_source(case):
    changed, ids = run(case)
    assert all(score(changed, ids, case).values())


@pytest.mark.parametrize("case", [case for case in CASES if case.target], ids=lambda case: case.id)
def test_complete_empty_response_and_a_checked_marker_do_not_hide_a_missed_event(case):
    changed, ids = run(case, omit=True)
    changed[KEY]["last_check"]["all_checked"] = True
    result = score(changed, ids, case)
    assert not result["required_state"]
    assert result["same_conditions"]


@pytest.mark.parametrize(
    "case", [case for case in CASES if not case.target], ids=lambda case: case.id
)
def test_exact_citation_and_valid_operation_do_not_establish_semantic_entailment(case):
    changed, ids = run(case, wrong=True)
    result = score(changed, ids, case)
    assert not result["required_state"]
    assert result["same_conditions"]
