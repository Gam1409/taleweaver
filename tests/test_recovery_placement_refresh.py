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
