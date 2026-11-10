"""An empty extraction is correct only for the unchanged member of a paired case."""

from types import SimpleNamespace

import pytest

from backend.engine.narrated_items.evidence import Catalog, bind
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.scene_continuity.ledger import apply
from backend.engine.scene_continuity.schema import KEY
from tests.scene_omission_cases import CASES, assess, initial


def run(case, *, omit=False):
    states, identifier = initial()
    message = SimpleNamespace(id="current", revision_id="current-v1", content=case.text)
    catalog = Catalog(case.text, case.room, scope=case.id)
    proposals = (
        [
            {
                "operation": "end",
                "record_id": identifier,
                "evidence": next(iter(catalog.narration_passages)),
            }
        ]
        if case.ended and not omit
        else []
    )
    result = bind(SharedItemExtraction(scene_updates=proposals), case.text, catalog=catalog)
    changed, errors = apply(
        states,
        result.scene_updates,
        [],
        message=message,
        scene_id="START",
        scene_description=case.room,
        session_id="session",
        minute=1,
        targets={"START", "KETTLE", "MILA", "__player__"},
    )
    assert not errors
    return changed, identifier, message


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_ground_truth_accepts_the_required_change_or_explicit_unchanged_control(case):
    changed, identifier, message = run(case)
    assert all(assess(changed, identifier, case, message).values())


@pytest.mark.parametrize("case", [case for case in CASES if case.ended], ids=lambda case: case.id)
def test_empty_output_and_a_checked_marker_cannot_hide_a_required_change(case):
    changed, identifier, message = run(case, omit=True)
    changed[KEY]["last_check"]["all_checked"] = True
    scores = assess(changed, identifier, case, message)
    assert not scores["required_state"] and not scores["source_occurrence"]
    assert scores["known_fact_preserved"]
