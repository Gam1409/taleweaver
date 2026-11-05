"""Pilot migrations preserve event provenance and reject incompatible readers."""

import pytest
from pydantic import ValidationError

from backend.engine.chpm.core.contracts import Snapshot
from backend.engine.chpm.core.replay import restore
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import accept, proposed


@pytest.mark.parametrize("with_experience", [False, True])
def test_v2_migration_preserves_full_projection_and_source_events(with_experience):
    mind = heard(text="You must obey")
    if with_experience:
        mind, _ = accept(mind, [proposed()])
    raw = mind.snapshot.model_dump()
    raw.update(schema_version=2, transition_version="evidence-ledger-v1")
    if not with_experience:
        raw.pop("experiences")
    migrated = restore(raw, expected_genesis=mind.genesis)
    assert migrated == mind.snapshot
    assert migrated.schema_version == 3
    assert migrated.transition_version == "evidence-ledger-v2"
    assert migrated.journal == mind.snapshot.journal
    assert migrated.evidence == mind.snapshot.evidence
    assert raw["schema_version"] == 2  # Input data is not mutated.


@pytest.mark.parametrize(
    "schema,transition", [(4, "evidence-ledger-v2"), (2, "future"), (3, "evidence-ledger-v1")]
)
def test_unknown_schema_transition_pairs_fail_closed(schema, transition):
    raw = heard().snapshot.model_dump()
    raw.update(schema_version=schema, transition_version=transition)
    with pytest.raises(ValidationError):
        Snapshot.model_validate(raw)


def test_migrated_experience_projection_still_requires_exact_replay():
    mind, _ = accept(heard(text="You must obey"), [proposed()])
    raw = mind.snapshot.model_dump()
    raw.update(schema_version=2, transition_version="evidence-ledger-v1", experiences=[])
    with pytest.raises(ValueError, match="projection disagrees"):
        restore(raw, expected_genesis=mind.genesis)
