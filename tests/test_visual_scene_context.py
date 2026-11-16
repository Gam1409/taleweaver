"""Neutral scene context survives the structured visual boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.clothing.frames import (
    Figure,
    FrameLighting,
    VisibleFrame,
    compose_frame,
    extract_frame,
)
from backend.engine.visual_novel.runtime import _npc_facts
from backend.engine.visual_text import visual_text


def test_visual_input_strips_sounds_but_keeps_emotions_and_story():
    source = "[angry] <breath> Stop! [playful] <giggles> Hello. [surprised] <short pause> The doctor enters. [NPC_1] <custom>"
    result = visual_text(source)
    for kept in (
        "[angry]",
        "[playful]",
        "[surprised]",
        "Stop!",
        "Hello.",
        "The doctor enters.",
        "[NPC_1]",
        "<custom>",
    ):
        assert kept in result
    for removed in ("<breath>", "<giggles>", "<short pause>"):
        assert removed not in result
    assert "<breath>" in source
    assert visual_text(result) == result


@pytest.mark.asyncio
async def test_frame_receives_emotion_without_vocal_noise(monkeypatch):
    from backend.engine.clothing import frames

    llm = SimpleNamespace(
        model="test", aexecute_complex_task=AsyncMock(return_value=VisibleFrame())
    )
    monkeypatch.setattr(frames.GameMasterLLM, "for_role", lambda *args: llm)
    await extract_frame(
        object(), "[surprised] <throat-clearing> The doctor enters.", [{"id": "DOC"}]
    )
    sent = json.loads(llm.aexecute_complex_task.call_args.args[1])["passage"]
    assert "[surprised]" in sent
    assert "<throat-clearing>" not in sent
    assert "The doctor enters." in sent


def test_visible_arrival_and_lighting_survive_composition():
    frame = VisibleFrame(
        lighting=FrameLighting(kind="morning daylight", source="window"),
        figures=[
            Figure(character_id="DOC", action="entering"),
            Figure(character_id="NURSE", presence="off_screen"),
        ],
    )
    result = compose_frame(frame, [{"id": "DOC"}, {"id": "NURSE"}], lighting="old lamp")
    assert result["lighting"] == "morning daylight, window"
    assert [person["id"] for person in result["characters"]] == ["DOC"]
    assert result["characters"][0]["action"] == "entering"
    assert result["characters"][0]["posture"] == "unspecified"


@pytest.mark.asyncio
async def test_relations_cannot_reintroduce_offscreen_character(monkeypatch):
    from backend.engine.clothing import frames

    llm = SimpleNamespace(
        model="test",
        aexecute_complex_task=AsyncMock(
            return_value={
                "figures": [{"character_id": "A"}, {"character_id": "B", "presence": "off_screen"}],
                "relations": [{"subject_id": "A", "target_id": "B", "relation": "beside"}],
            }
        ),
    )
    monkeypatch.setattr(frames.GameMasterLLM, "for_role", lambda *args: llm)
    with pytest.raises(ValueError, match="absent character"):
        await extract_frame(object(), "B has left.", [{"id": "A"}, {"id": "B"}])


def test_snapshot_resolves_existing_coat_metadata_and_keeps_position():
    profile = {"version": 1, "worn": [{"item_id": "COAT"}]}
    npc = SimpleNamespace(
        id="NPC",
        name="Nurse",
        inventory=[],
        metadata_json={"inventory": ["COAT"]},
        visual_profile=profile,
        entity_type="NPC",
    )
    coat = SimpleNamespace(
        id="COAT", name="Blue coat", description="", metadata_json={}, entity_type="OBJECT"
    )
    state = SimpleNamespace(
        entity_states={
            "COAT": {"clothing": {"layer": 2, "coverage": ["torso", "arms"], "opaque": True}}
        }
    )
    result = _npc_facts(
        {"id": "NPC", "spatial_position": "beside the window"},
        {"NPC": npc, "COAT": coat},
        state,
        False,
    )
    assert "Blue coat" in result["clothing"]
    assert result["position"] == "beside the window"
    # Explicit empty ownership must override the legacy inventory.
    state.entity_states["NPC"] = {"inventory": []}
    result = _npc_facts({"id": "NPC"}, {"NPC": npc, "COAT": coat}, state, False)
    assert "Blue coat" not in result["clothing"]
