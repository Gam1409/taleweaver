"""The reviewable examples and exported JSON schemas agree with their consumers."""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.engine.agent_runtime_contract import KNOWN_FEATURES, inspect_manifest
from backend.engine.chpm.schema import KernelState
from backend.engine.living_world.schema import Simulation
from backend.schemas.agent_runtime import AgentRuntime, NpcAgentRuntime

ROOT = Path(__file__).parents[1] / "docs" / "specs" / "agent_runtime"


@pytest.mark.parametrize("name", ["minimal.adv", "full.adv"])
def test_authored_examples_validate_as_json_schema_and_runtime_contract(name):
    payload = json.loads((ROOT / "examples" / name).read_text())
    schema = json.loads((ROOT / "v1.schema.json").read_text())
    npc_schema = json.loads((ROOT / "npc-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(npc_schema)
    Draft202012Validator(schema).validate(payload["extensions"]["agent_runtime"])
    for npc in payload["npcs"]:
        Draft202012Validator(npc_schema).validate(npc["metadata_json"]["agent_runtime"])
    assert inspect_manifest(payload, KNOWN_FEATURES).status == "ready"


def test_generated_schemas_are_current():
    for name, model in (("v1.schema.json", AgentRuntime), ("npc-v1.schema.json", NpcAgentRuntime)):
        saved = json.loads((ROOT / name).read_text())
        saved.pop("$schema")
        assert saved == model.model_json_schema()


def test_session_fragment_uses_existing_state_owners():
    payload = json.loads((ROOT / "examples" / "session-state.fragment.json").read_text())
    state = payload["session_state"]
    assert (
        KernelState.model_validate(state["entity_states"]["__chpm__"])
        .minds["GUIDE"]
        .snapshot.cursor
        == 0
    )
    assert Simulation.model_validate(state["living_world"]).cursor == state["in_game_time"]
    assert "extensions" not in payload


def test_future_version_is_not_activated_and_corpus_hash_pins_exact_bytes():
    future = json.loads((ROOT / "examples" / "unknown-version.adv").read_text())
    assert inspect_manifest(future, KNOWN_FEATURES).status == "unsupported_version"
    full = json.loads((ROOT / "examples" / "full.adv").read_text())
    corpus = full["extensions"]["agent_runtime"]["rag"]["corpora"][0]
    assert (
        hashlib.sha256((ROOT / "examples" / "harbor-lore.empty.json").read_bytes()).hexdigest()
        == corpus["sha256"]
    )
