"""Historical placement evidence must update an already registered worn garment."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.clothing.recovery_correction import RecoveryCorrection
from backend.engine.clothing.recovery_evaluation import evaluate
from backend.engine.clothing.recovery_schema import RecoveryProposal
from tests.test_narrated_items import fixtures


def context(text, *, exposed=()):
    actors, snapshot = fixtures()
    actor = actors["NPC"]
    actor["visual_profile"]["worn"][0]["uncovered_regions"] = list(exposed)
    return {
        "actor": actor,
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": text}],
    }


def proposal(text, *, regions=(), placement=None):
    return RecoveryProposal.model_validate(
        {
            "entries": [
                {
                    "source_message_id": "source",
                    "action": {
                        "item_id": "SHIRT",
                        "source_owner": "NPC",
                        "destination_owner": "NPC",
                        "basis": "observed_wear",
                        "disposition": "worn",
                        "evidence": text,
                    },
                    "uncovered_regions": list(regions),
                    "placement_evidence": text if placement is None else placement,
                    "restore_coverage": not regions and placement != "",
                }
            ]
        }
    )


@pytest.mark.parametrize(
    "before,after,text",
    [
        ((), ("torso",), "Anna lifts her shirt above her waist."),
        (("torso",), (), "Anna lowers her shirt to cover her waist again."),
    ],
)
def test_history_can_restore_changed_placement_without_recreating_the_garment(before, after, text):
    source = context(text, exposed=before)
    untouched = deepcopy(source)
    changed, accepted, errors, skipped = evaluate(
        source, proposal(text, regions=after), True, "session"
    )
    assert not errors and not skipped
    assert len(accepted) == 1 and accepted[0]["item"]["id"] == "SHIRT"
    assert changed["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] == list(after)
    assert len(changed["NPC"]["inventory"]) == 1
    assert source == untouched


def test_omitted_placement_never_resets_an_existing_exposed_region():
    text = "Anna speaks quietly while still wearing her shirt."
    source = context(text, exposed=("torso",))
    changed, accepted, errors, _ = evaluate(source, proposal(text, placement=""), True, "session")
    assert not errors and not accepted
    assert changed["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] == ["torso"]


def test_manual_full_coverage_requires_explicit_intent_and_a_quote():
    body = {
        "status": "worn",
        "evidence": "She wears the shirt.",
        "placement_evidence": "She lowers the shirt.",
    }
    with pytest.raises(ValidationError):
        RecoveryCorrection.model_validate(body)
    restored = RecoveryCorrection.model_validate({**body, "restore_coverage": True})
    assert restored.restore_coverage and restored.uncovered_regions == []
    with pytest.raises(ValidationError):
        RecoveryCorrection.model_validate({**body, "restore_coverage": True, "status": "carried"})
    with pytest.raises(ValidationError):
        RecoveryCorrection.model_validate(
            {**body, "restore_coverage": True, "uncovered_regions": ["torso"]}
        )


def test_full_coverage_reset_also_requires_literal_placement_evidence():
    text = "Anna speaks quietly while still wearing her shirt."
    source = context(text, exposed=("torso",))
    _, accepted, errors, _ = evaluate(
        source, proposal(text, placement="She covers her waist."), True, "session"
    )
    assert not accepted and errors


def test_placement_recovery_preserves_the_original_acquisition_source():
    text = "Anna lifts her shirt above her waist."
    source = context(text)
    origin = {"kind": "narrated", "source_message_id": "original-acquisition"}
    source["snapshot"].items["SHIRT"]["item_origin"] = deepcopy(origin)
    changed, accepted, errors, _ = evaluate(
        source, proposal(text, regions=("torso",)), True, "session"
    )
    assert not errors and len(accepted) == 1
    assert accepted[0]["source_message_id"] == "source"
    assert accepted[0]["item"]["item_origin"] == origin
    assert changed["NPC"]["inventory"][0]["item_origin"] == origin


@pytest.mark.parametrize("age,detailed", [(17, True), (None, True), (30, False)])
def test_existing_inner_garment_placement_keeps_age_and_detail_guards(age, detailed):
    text = "Anna adjusts the fabric to uncover her waist."
    source = context(text)
    source["actor"]["age_years"] = age
    source["actor"]["visual_profile"]["appearance"]["age_years"] = age
    source["snapshot"].items["SHIRT"]["clothing"]["underwear"] = True
    before = deepcopy(source)
    _, accepted, errors, skipped = evaluate(
        source, proposal(text, regions=("torso",)), detailed, "session"
    )
    assert not accepted and not errors and skipped
    assert source == before
