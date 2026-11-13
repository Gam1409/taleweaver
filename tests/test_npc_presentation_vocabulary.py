"""Narrator-authored feelings and numeric colors remain bounded presentation data."""

import json
from unittest.mock import Mock

import pytest

from backend.core.npc_presentation import PortraitPreferences, public_cues
from backend.engine.npc_presentation import runtime
from backend.engine.npc_presentation.runtime import PresentationTurn

BODY = "The archivist admits that the unfamiliar task feels difficult."
THOUGHT = "I would appreciate some reassurance."
ENTRY = {
    "npc_id": "KEEPER",
    "emotion": "vulnerability",
    "intensity": 65,
    "color_rgb": [140, 160, 210],
    "thought": THOUGHT,
}


def response(entries):
    return BODY + "<npc-state>" + json.dumps({"npcs": entries}) + "</npc-state>"


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("thoughts", [False, True])
def test_freeform_feeling_and_numeric_color_survive_source_bound_publication(streamed, thoughts):
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=thoughts),
        {"KEEPER": "Archivist"},
    )
    raw = response([ENTRY])
    visible = (
        "".join(turn.feed(char) for char in raw) + turn.finish() if streamed else turn.clean(raw)
    )
    assert visible == BODY
    expected = {"emotion": "vulnerability", "intensity": 65, "color_rgb": [140, 160, 210]}
    if thoughts:
        expected["thought"] = THOUGHT
    payload = turn.payload(visible)
    assert payload is not None
    assert payload["npcs"] == {"KEEPER": expected}
    assert public_cues(payload, visible) == payload
    assert public_cues(payload, "A rewritten reply.") is None
    assert turn.payload("The next unassessed reply.") is None
    assert PresentationTurn(turn.preferences, turn.catalog).payload(visible) is None


@pytest.mark.parametrize("invalid", ["", "   ", 7, True, ["joy"], "x" * 81, None])
def test_invalid_feeling_preserves_thought_and_independent_valid_sibling(invalid):
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True),
        {"KEEPER": "Archivist", "VISITOR": "Visitor"},
    )
    turn.clean(response([{**ENTRY, "emotion": invalid}, {**ENTRY, "npc_id": "VISITOR"}]))
    assert turn.payload(BODY)["npcs"] == {
        "KEEPER": {"thought": THOUGHT},
        "VISITOR": {
            "emotion": "vulnerability",
            "intensity": 65,
            "color_rgb": [140, 160, 210],
            "thought": THOUGHT,
        },
    }


def test_disabled_palette_does_not_restore_emotion_from_supported_metadata():
    turn = PresentationTurn(PortraitPreferences(character_thoughts=True), {"KEEPER": "Archivist"})
    turn.clean(response([ENTRY]))
    assert turn.payload(BODY)["npcs"] == {"KEEPER": {"thought": THOUGHT}}


@pytest.mark.parametrize(
    "invalid",
    [
        "red",
        "var(--danger)",
        [-1, 0, 0],
        [0, 256, 0],
        [True, 0, 0],
        [1.5, 0, 0],
        ["1", 0, 0],
        [0, 0],
        [0, 0, 0, 0],
        {},
        [],
    ],
)
def test_invalid_color_drops_only_the_color_and_preserves_the_assessment(invalid, monkeypatch):
    rejection = Mock()
    monkeypatch.setattr(runtime, "reject", rejection)
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True),
        {"KEEPER": "Archivist"},
    )
    turn.clean(response([{**ENTRY, "color_rgb": invalid}]))
    assert turn.payload(BODY)["npcs"] == {
        "KEEPER": {"emotion": "vulnerability", "intensity": 65, "thought": THOUGHT}
    }
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", "presentation.invalid_color")


@pytest.mark.parametrize("name", ["adoration", "mixed relief and worry", "Смятение", "🌤" * 80])
def test_arbitrary_bounded_labels_and_legacy_cues_without_rgb_remain_valid(name):
    turn = PresentationTurn(PortraitPreferences(emotion_palette=True), {"KEEPER": "Archivist"})
    turn.clean(response([{**ENTRY, "emotion": name, "color_rgb": None}]))
    payload = turn.payload(BODY)
    assert payload["npcs"] == {"KEEPER": {"emotion": name, "intensity": 65}}
    assert public_cues(payload, BODY) == payload
    corrupt = {
        **payload,
        "npcs": {"KEEPER": {"emotion": name, "intensity": 65, "color_rgb": [300, 0, 0]}},
    }
    assert public_cues(corrupt, BODY) is None


def test_invalid_thought_does_not_discard_valid_emotion_and_color():
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True),
        {"KEEPER": "Archivist"},
    )
    turn.clean(response([{**ENTRY, "thought": "x" * 161}]))
    assert turn.payload(BODY)["npcs"] == {
        "KEEPER": {"emotion": "vulnerability", "intensity": 65, "color_rgb": [140, 160, 210]}
    }


@pytest.mark.parametrize("color_rgb", [[0, 0, 0], [255, 255, 255], [0, 255, 128]])
def test_numeric_color_channel_boundaries_round_trip(color_rgb):
    turn = PresentationTurn(PortraitPreferences(emotion_palette=True), {"KEEPER": "Archivist"})
    turn.clean(response([{**ENTRY, "emotion": "  mixed relief  ", "color_rgb": color_rgb}]))
    payload = turn.payload(BODY)
    assert payload["npcs"] == {
        "KEEPER": {"emotion": "mixed relief", "intensity": 65, "color_rgb": color_rgb}
    }
    assert public_cues(payload, BODY) == payload
