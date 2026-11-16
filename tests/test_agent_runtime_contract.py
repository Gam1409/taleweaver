"""Version, capability and reference negotiation never activates optional infrastructure."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.agent_runtime_contract import (
    KNOWN_FEATURES,
    inspect_manifest,
    inspect_runtime,
    known_projection,
    validate_npcs,
)
from backend.schemas.agent_runtime import AgentRuntime, NpcAgentRuntime


@pytest.mark.parametrize("version", [None, True, "1", 1.0])
def test_version_is_explicit_strict_integer(version):
    assert inspect_runtime({"schema_version": version}).status == "invalid"


@pytest.mark.parametrize("version", [0, 2, 999])
def test_unsupported_version_is_preserved_but_never_activated(version):
    raw = {"schema_version": version, "future": {"keep": None}}
    before = deepcopy(raw)
    assert inspect_runtime(raw, KNOWN_FEATURES).status == "unsupported_version"
    assert raw == before


def test_legacy_and_minimal_contract():
    assert inspect_runtime(None).status == "absent"
    result = inspect_runtime({"schema_version": 1})
    assert result.status == "ready"
    assert not result.active_features


@pytest.mark.parametrize("extensions", [[], None, "invalid"])
def test_malformed_manifest_namespace_is_reported_without_exception(extensions):
    assert inspect_manifest({"extensions": extensions}).status == "invalid"


def test_malformed_npc_metadata_is_reported_without_exception():
    result = inspect_manifest({"npcs": [{"id": "NPC", "metadata_json": ["invalid"]}]})
    assert result.status == "invalid"


def test_npc_namespace_requires_adventure_contract():
    result = inspect_manifest(
        {"npcs": [{"id": "NPC", "metadata_json": {"agent_runtime": {"schema_version": 1}}}]}
    )
    assert result.status == "invalid"


def test_required_unknown_blocks_and_optional_unknown_is_ignored():
    required = inspect_runtime({"schema_version": 1, "required_features": ["future.v1"]})
    assert required.status == "missing_required"
    assert required.missing_required == {"future.v1"}
    assert not required.active_features
    optional = inspect_runtime({"schema_version": 1, "optional_features": ["future.v1"]})
    assert optional.status == "ready"
    assert optional.ignored_optional == {"future.v1"}


def test_unknown_fields_survive_storage_but_not_execution_projection():
    raw = {
        "schema_version": 1,
        "future": {"nullable": None},
        "autonomy": {"future_mode": "ignore"},
    }
    result = inspect_runtime(raw)
    assert set(result.unknown_fields) == {
        "agent_runtime.future",
        "agent_runtime.autonomy.future_mode",
    }
    assert result.config.model_dump()["future"] == raw["future"]
    assert "future" not in known_projection(result.config)
    assert "future_mode" not in known_projection(result.config)["autonomy"]


def test_capability_is_never_assumed_and_child_needs_parent():
    raw = {
        "schema_version": 1,
        "optional_features": ["living_world.v1", "living_world.catch_up.v1"],
        "living_world": {"enabled": True, "absence_mode": "catch_up"},
    }
    assert not inspect_runtime(raw).active_features
    child_only = frozenset({"living_world.catch_up.v1"})
    assert not inspect_runtime(raw, child_only).active_features
    assert inspect_runtime(raw, KNOWN_FEATURES).active_features == set(raw["optional_features"])


@pytest.mark.parametrize(
    "updates",
    [
        {"autonomy": {"enabled": "true"}},
        {"autonomy": {"enabled": True}},
        {"required_features": ["x.v1", "x.v1"]},
        {"required_features": ["x.v1"], "optional_features": ["x.v1"]},
        {"required_features": ["library.remote.v1"]},
        {"rag": {"top_k": 0}},
        {"living_world": {"max_events": 129}},
    ],
)
def test_invalid_configuration_has_no_executable_projection(updates):
    assert inspect_runtime({"schema_version": 1, **updates}, KNOWN_FEATURES).status == "invalid"


def test_npc_seed_is_static_and_relationship_target_is_checked():
    raw = {
        "schema_version": 1,
        "initial_state": {"relationships": [{"target_id": "B", "description": "Old friend"}]},
    }
    npcs = [{"id": "A", "metadata_json": {"agent_runtime": raw}}, {"id": "B"}]
    assert validate_npcs({"npcs": npcs})["A"].initial_state.relationships[0].target_id == "B"
    with pytest.raises(ValueError, match="target"):
        validate_npcs({"npcs": npcs[:1]})
    with pytest.raises(ValueError, match="unique"):
        validate_npcs({"npcs": [npcs[0], npcs[0]]})


def test_npc_version_rejects_bool_and_future_versions():
    for version in (True, 2):
        with pytest.raises(ValidationError):
            NpcAgentRuntime.model_validate({"schema_version": version})


def test_required_remote_resource_requires_both_capabilities():
    raw = {
        "schema_version": 1,
        "required_features": ["rag.observer.v1"],
        "optional_features": ["library.remote.v1"],
        "rag": {
            "enabled": True,
            "corpora": [
                {
                    "id": "lore",
                    "source": "remote",
                    "library_id": "community",
                    "revision": "r1",
                    "sha256": "a" * 64,
                    "required": True,
                }
            ],
        },
    }
    with pytest.raises(ValidationError, match="remote library"):
        AgentRuntime.model_validate(raw)
