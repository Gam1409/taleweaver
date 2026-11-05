"""Bounded views keep current evidence and identity; budgets never rewrite history."""

import pytest

from backend.engine.chpm import cognitive_context, experience, inference, motivation, prompts
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS, GroundedProposal
from backend.engine.chpm.host_state import record
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Settings
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_host_state import source
from tests.test_chpm_kernel import observation


def test_large_history_packs_without_changing_sources_or_required_fields():
    value = None
    for number in range(40):
        value = heard(value, f"m{number}", f"Episode {number}. " + "A remembered report. " * 45)
        window = cognitive_context.appraisal_context.build(value)
        alias = next(reversed(window.sources))
        value = accept(
            value,
            [
                proposal(
                    statement=f"Expectation about episode {number}",
                    citations=[{"source_id": alias, "quote": f"Episode {number}."}],
                )
            ],
            f"m{number}",
        )
    current = observation().model_copy(
        update={"message_id": "current", "player_request": "Speak freely"}
    )
    for number in range(4):
        item = source("current", text=f"Current trigger {number}. " + "visible " * 120).model_copy(
            update={"kind": "world_event" if number == 0 else "speech", "speaker_id": "@player"}
        )
        value = record(value, item, minute=value.snapshot.sim_minute)
    supplied = {
        "authored_character": value.genesis.identity.description,
        "authored_goal": value.genesis.identity.authored_goals[0],
        "own_previous_words": "Previous words. " * 100,
        "witnessed_utterances_not_world_facts": [{"quote": "Old quote. " * 100}] * 12,
        "observation": current.model_dump(),
    }
    original = value.model_dump_json()
    settings = Settings()
    instruction = prompts.PROPOSE + INSTRUCTIONS + motivation.INSTRUCTIONS + experience.INSTRUCTIONS
    window, _, payload, ids = cognitive_context.pack(
        value, current, supplied, [], settings, instruction
    )
    system, content = inference.compose(instruction, payload, GroundedProposal, ids)
    assert len(system) + len(content) <= 24000
    assert payload["context_packing"]["tier"] > 0
    assert payload["context_packing"]["dialogue_entries_omitted"] > 0
    assert len([s for _, s, _ in window.sources.values() if s.message_id == "current"]) == 4
    assert payload["authored_character"] == supplied["authored_character"]
    assert payload["observation"] == supplied["observation"]
    assert settings.max_input_chars == 24000 and value.model_dump_json() == original
    with pytest.raises(ChpmError, match="No request was sent"):
        cognitive_context.pack(
            value, current, supplied, [], Settings(max_input_chars=8000), instruction
        )
