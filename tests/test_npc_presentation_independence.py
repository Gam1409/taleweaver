"""Personality admission controls decisions, not independently enabled narrator cues."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.core.npc_presentation import PortraitPreferences
from backend.engine.chpm import continuation, runtime
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.npc_presentation.runtime import PresentationTurn
from tests.test_chpm_kernel import decision

TEXT = "Mila continues the discussion while Rin waits silently."
FOOTER = '<npc-state>{"npcs":[{"npc_id":"npc","emotion":"fear","intensity":80,"thought":"I need a moment to steady myself."},{"npc_id":"peer","emotion":"interest","intensity":60,"thought":"Explain the next step."}]}</npc-state>'


@pytest.mark.parametrize("capture_first", [False, True])
@pytest.mark.parametrize("recover", [False, True])
async def test_cached_partial_or_simplified_preparation_cannot_veto_narrator_cues(
    capture_first, recover
):
    presentation = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True),
        {"npc": "Rin", "peer": "Mila"},
    )
    state = KernelState(settings=Settings(mode="live", actor_ids=["npc", "peer"]))
    value = runtime.Turn(state, "input")
    value.decisions = {"peer": decision().model_copy(update={"actor_id": "peer"})}
    value.names = {"peer": "Mila"}
    value.deferred_names = {"npc": "Rin"}
    value.usage.actor_failures = {"npc": "The completed proposal was rejected."}
    manager = SimpleNamespace(
        state=SimpleNamespace(entity_states={KEY: state.model_dump()}),
        adventure={"rule_enforcement_mode": "vn"},
        _vn_player_message_id="input",
        _chpm_turn=value,
        _portrait_presentation=presentation,
    )
    before = deepcopy(manager.state.entity_states)
    if capture_first:
        assert presentation.clean(TEXT + FOOTER) == TEXT
    await runtime.prepare(manager, "Continue.", [])
    if recover:
        continuation.activate(value, "review_unavailable")
        await runtime.prepare(manager, "Continue.", [])
    if not capture_first:
        assert presentation.clean(TEXT + FOOTER) == TEXT
    original = deepcopy(presentation.candidates)
    payload = presentation.payload(TEXT)
    assert set(payload["npcs"]) == {"npc", "peer"}
    assert payload["npcs"]["npc"]["emotion"] == "fear"
    assert payload["npcs"]["npc"]["thought"] == "I need a moment to steady myself."
    assert presentation.candidates == original
    assert presentation.diagnostic(TEXT, completed=True) == "available"
    assert presentation.payload("Different unassessed narration.") is None
    assert manager.state.entity_states == before
