"""A rejected character's private cues cannot leak into an otherwise reviewed reply."""

from copy import deepcopy
from types import SimpleNamespace

from backend.core.npc_presentation import PortraitPreferences
from backend.engine.npc_presentation.runtime import PresentationTurn, defer_characters

TEXT = "Mila continues the discussion."
FOOTER = '<npc-state>{"npcs":[{"npc_id":"npc","emotion":"fear","intensity":80,"thought":"New unconfirmed thought."},{"npc_id":"peer","emotion":"interest","intensity":60,"thought":"Explain the next step."}]}</npc-state>'


def presentation():
    return PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True),
        {"npc": "Rin", "peer": "Mila"},
    )


def test_deferred_cues_are_filtered_even_if_a_candidate_was_already_captured():
    turn = presentation()
    assert turn.clean(TEXT + FOOTER) == TEXT
    original = deepcopy(turn.candidates)
    defer_characters(SimpleNamespace(_portrait_presentation=turn), {"npc"})
    payload = turn.payload(TEXT)
    assert set(payload["npcs"]) == {"peer"}
    assert payload["npcs"]["peer"]["thought"] == "Explain the next step."
    assert turn.candidates == original
    assert turn.diagnostic(TEXT, completed=True) == "available"


def test_filtering_all_cues_is_unassessed_instead_of_a_source_hash_error():
    turn = presentation()
    turn.clean(TEXT + FOOTER)
    defer_characters(SimpleNamespace(_portrait_presentation=turn), {"npc", "peer"})
    assert turn.payload(TEXT) is None
    assert turn.diagnostic(TEXT, completed=True) == "no_valid_entries"


def test_deferred_actor_is_ignored_by_new_capture_without_losing_its_peer():
    turn = presentation()
    defer_characters(SimpleNamespace(_portrait_presentation=turn), {"npc"})
    turn.clean(TEXT + FOOTER)
    assert set(turn.payload(TEXT)["npcs"]) == {"peer"}
    assert turn.payload("A different response.") is None
    assert turn.catalog == {"npc": "Rin", "peer": "Mila"}


def test_deferral_is_local_to_its_presentation_and_does_not_require_display_options():
    first, second = presentation(), presentation()
    defer_characters(SimpleNamespace(_portrait_presentation=first), {"npc"})
    defer_characters(SimpleNamespace(), {"npc"})
    second.clean(TEXT + FOOTER)
    assert set(second.payload(TEXT)["npcs"]) == {"npc", "peer"}
