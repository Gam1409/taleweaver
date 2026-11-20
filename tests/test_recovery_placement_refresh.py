"""Reviewed placement observations refresh proof without recreating a known garment."""

from copy import deepcopy
from hashlib import sha256

import pytest

from backend.engine.clothing.recovery_evaluation import evaluate
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryProposal
from tests.test_narrated_items import fixtures

TEXT = "Anna's blue shirt remains raised above her waist."


def context(source):
    actors, snapshot = fixtures()
    actor = actors["NPC"]
    actor["visual_profile"]["worn"][0].update(uncovered_regions=["torso"], source=source)
    return {
        "actor": actor,
        "snapshot": snapshot,
        "messages": [{"id": "current-source", "role": "assistant", "content": TEXT}],
    }


def proposal():
    return RecoveryProposal(
        entries=[
            RecoveryEntry.model_validate(
                {
                    "source_message_id": "current-source",
                    "action": {
                        "source_owner": "NPC",
                        "destination_owner": "NPC",
                        "item_id": "SHIRT",
                        "basis": "observed_wear",
                        "disposition": "worn",
                        "evidence": TEXT,
                    },
                    "uncovered_regions": ["torso"],
                    "placement_evidence": TEXT,
                }
            )
        ]
    )


@pytest.mark.parametrize("stale", ["missing", "hash", "role", "quote", "span"])
def test_existing_displacement_can_refresh_missing_or_changed_source_proof(stale):
    source = {
        "source_message_id": "current-source",
        "content_hash": sha256(TEXT.encode()).hexdigest(),
        "evidence": TEXT,
    }
    if stale == "missing":
        source["source_message_id"] = "unavailable-source"
    elif stale == "hash":
        source["content_hash"] = "0" * 64
    elif stale == "role":
        source["source_role"] = "user"
    elif stale == "quote":
        source["evidence"] = "An older description of the shirt."
    else:
        source["evidence_span"] = {"start": 0, "end": 4}
    original = context(source)
    before = deepcopy(original["actor"])
    changed, accepted, errors, skipped = evaluate(original, proposal(), True, "session")
    assert not errors and not skipped and len(accepted) == 1
    row = changed["NPC"]["visual_profile"]["worn"][0]
    assert row["item_id"] == "SHIRT" and row["uncovered_regions"] == ["torso"]
    assert row["source"]["source_message_id"] == "current-source"
    assert row["source"]["content_hash"] == sha256(TEXT.encode()).hexdigest()
    assert row["source"]["evidence"] == TEXT
    assert changed["NPC"]["inventory"] == before["inventory"]
    assert original["actor"] == before


def test_a_current_exact_proof_is_a_noop_and_no_proposal_never_changes_state():
    source = {
        "source_message_id": "current-source",
        "content_hash": sha256(TEXT.encode()).hexdigest(),
        "evidence": TEXT,
    }
    current = context(source)
    before = deepcopy(current["actor"])
    for response in (proposal(), RecoveryProposal()):
        changed, accepted, errors, skipped = evaluate(current, response, True, "session")
        assert not accepted and not errors and not skipped
        assert changed["NPC"] == before


@pytest.mark.parametrize("known_regions", [[], ["torso"]])
def test_coarse_recovery_retains_known_regions_until_evidenced_restoration(known_regions):
    text = "Anna has slipped one arm out of her shirt."
    current = context(None)
    current["messages"][0]["content"] = text
    current["actor"]["visual_profile"]["worn"][0]["uncovered_regions"] = known_regions
    data = proposal().entries[0].model_dump()
    data["action"]["evidence"] = text
    data.update(partially_removed=True, uncovered_regions=[], placement_evidence=text)
    coarse = RecoveryProposal(entries=[RecoveryEntry.model_validate(data)])
    changed, accepted, errors, skipped = evaluate(current, coarse, True, "session")
    assert not errors and not skipped
    assert accepted[0]["partially_removed"] is True
    row = changed["NPC"]["visual_profile"]["worn"][0]
    assert row["partially_removed"] and row["uncovered_regions"] == known_regions
    assert row["source"]["evidence"] == text
    current["actor"] = changed["NPC"]
    assert not evaluate(current, coarse, True, "session")[1]
    data.update(partially_removed=False, placement_evidence="")
    unchanged = RecoveryProposal(entries=[RecoveryEntry.model_validate(data)])
    assert not evaluate(current, unchanged, True, "session")[1]
    normal = "Anna pulls the shirt fully back into place."
    current["messages"][0]["content"] = normal
    data["action"]["evidence"] = normal
    data.update(restore_coverage=True, placement_evidence=normal)
    restored = RecoveryProposal(entries=[RecoveryEntry.model_validate(data)])
    changed, accepted, errors, skipped = evaluate(current, restored, True, "session")
    assert accepted and not errors and not skipped
    assert changed["NPC"]["visual_profile"]["worn"] == [
        {"item_id": "SHIRT", "uncovered_regions": []}
    ]


def test_coarse_recovery_requires_exact_placement_evidence():
    current = context(None)
    data = proposal().entries[0].model_dump()
    data.update(partially_removed=True, uncovered_regions=[], placement_evidence="")
    for evidence in ("", TEXT[:3], "Not a quote from the source."):
        data["placement_evidence"] = evidence
        changed, accepted, errors, _ = evaluate(
            current, RecoveryProposal(entries=[RecoveryEntry.model_validate(data)]), True, "session"
        )
        assert errors and not accepted and changed["NPC"] == current["actor"]
