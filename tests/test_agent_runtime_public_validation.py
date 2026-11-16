"""Public-copy validation checks both scopes without weakening opaque transport."""

from copy import deepcopy

import pytest

from backend.engine.adventure_compat import CompatibilityError, export_upstream_manifest
from backend.engine.agent_runtime_contract import inspect_manifest
from tests.test_agent_runtime_portability import manifest


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize(
    "seed",
    [
        {},
        {"schema_version": 99},
        {"schema_version": True},
        {"schema_version": 1, "autonomy": "unsupported"},
        {
            "schema_version": 1,
            "initial_state": {"relationships": [{"target_id": "MISSING", "description": "Friend"}]},
        },
    ],
)
def test_public_copy_rejects_invalid_npc_even_when_capability_is_missing(seed, required):
    source = manifest()
    source["npcs"][0]["metadata_json"]["agent_runtime"] = seed
    if required:
        source["extensions"]["agent_runtime"]["required_features"] = ["future.v1"]
    before = deepcopy(source)
    with pytest.raises(CompatibilityError):
        export_upstream_manifest(source)
    assert source == before
    assert inspect_manifest(source).status == "invalid"


def test_npc_only_namespace_cannot_silently_skip_public_runtime_validation():
    source = manifest()
    del source["extensions"]["agent_runtime"]
    with pytest.raises(CompatibilityError):
        export_upstream_manifest(source)


def test_valid_missing_capability_can_offer_explicit_core_fallback():
    source = manifest()
    source["extensions"]["agent_runtime"]["required_features"] = ["future.v1"]
    converted, report = export_upstream_manifest(source)
    assert inspect_manifest(source).status == "missing_required"
    assert converted["npcs"] == source["npcs"]
    assert report.requires_acknowledgement
