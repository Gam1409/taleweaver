"""Optional desire is an appraisal, never consent, attachment or a personality edit."""

import pytest

from backend.engine.chpm import experience
from backend.engine.chpm.core.replay import restore
from backend.engine.chpm.host_state import before_messages
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import accept, proposed

TRIGGER = "We can share a quiet moment together."


def desire(**changes):
    return proposed(
        dimension="sexual_desire",
        citations=[{"source_id": "e1", "quote": TRIGGER}],
        explanation="The invitation may evoke attraction without a decision to act.",
        alternatives=["May prefer companionship only"],
        unknowns=["Whether to act on the feeling"],
        **changes,
    )


@pytest.mark.parametrize("target", [None, "@player"])
def test_directed_or_unspecified_desire_uses_existing_sources_without_rewriting_identity(target):
    before = heard(text=TRIGGER)
    after, ids = accept(before, [desire(about_id=target)])
    state = after.snapshot.experiences[0]
    assert state.dimension == "sexual_desire" and state.about_id == target
    assert len(ids) == 1 and state.level == "moderate"
    assert after.genesis == before.genesis
    assert after.snapshot.beliefs == before.snapshot.beliefs
    assert restore(after.snapshot.model_dump(), expected_genesis=before.genesis) == after.snapshot
    assert before_messages(after, {"m1"}).snapshot.experiences == ()
    assert experience.view(after)["states"][0]["dimension"] == "sexual_desire"


def test_omitted_desire_is_not_inferred_from_arousal_and_absence_can_be_explicit():
    before = heard(text=TRIGGER)
    arousal = proposed(dimension="arousal", citations=[{"source_id": "e1", "quote": TRIGGER}])
    activated, _ = accept(before, [arousal])
    assert [s.dimension for s in activated.snapshot.experiences] == ["arousal"]
    changed, _ = accept(before, [arousal, desire(level="absent")])
    assert {(s.dimension, s.level) for s in changed.snapshot.experiences} == {
        ("arousal", "moderate"),
        ("sexual_desire", "absent"),
    }


def test_desire_still_requires_current_evidence_and_a_known_target():
    before = heard(text=TRIGGER)
    original = before.model_dump_json()
    with pytest.raises(ValueError, match="unavailable subject"):
        accept(before, [desire(about_id="unseen-npc")])
    with pytest.raises(ValueError, match="current observed trigger"):
        accept(before, [desire()], message="another-turn")
    with pytest.raises(ValueError):
        desire(consent=True)
    assert before.model_dump_json() == original
