"""Exact source occurrence metadata survives copy and remains unavailable without history."""

from types import SimpleNamespace

import pytest

from backend.engine.narrated_items.evidence import stamp
from backend.engine.narrated_items.runtime import KEY
from backend.engine.scene_staging.state import digest
from backend.engine.visual_novel.lifecycle import remap_social_state


def test_item_source_points_to_saved_assistant_and_cannot_be_rebound_to_later_quote():
    text = "The kettle starts heating."
    state = SimpleNamespace(
        entity_states={
            KEY: {
                "message_id": "input",
                "source_hash": digest(text),
                "processed_message_ids": ["input"],
            }
        }
    )
    manager = SimpleNamespace(state=state, _vn_player_message_id="input")
    first = SimpleNamespace(id="original", revision_id="revision", content=text)
    stamp(manager, first)
    assert state.entity_states[KEY]["narration_source"]["message_id"] == "original"
    stamp(manager, SimpleNamespace(id="later", revision_id="another", content=text))
    assert state.entity_states[KEY]["narration_source"]["message_id"] == "original"
    copied = remap_social_state(state.entity_states, {"original": "copy", "input": "copy-input"})
    assert copied[KEY]["narration_source"]["message_id"] == "copy"
    assert copied[KEY]["message_id"] == "copy-input"
    assert copied[KEY]["processed_message_ids"] == ["copy-input"]
    missing = remap_social_state(state.entity_states, {"input": "copy-input"})
    assert missing[KEY]["narration_source"]["message_id"] is None
    assert missing[KEY]["narration_source"]["available"] is False
    assert missing[KEY]["narration_source"]["content_hash"] == digest(text)


def test_unknown_old_item_check_shape_does_not_break_source_capture():
    state = SimpleNamespace(entity_states={KEY: "unsupported old state"})
    manager = SimpleNamespace(state=state, _vn_player_message_id="input")
    stamp(manager, SimpleNamespace(id="reply", revision_id="r", content="Some text."))
    assert state.entity_states[KEY] == "unsupported old state"
    copied = remap_social_state(
        {
            KEY: {
                "message_id": {},
                "processed_message_ids": [{}, "input"],
                "narration_source": {"message_id": []},
            }
        },
        {"input": "copied"},
    )
    assert copied[KEY]["processed_message_ids"] == ["copied"]
    assert copied[KEY]["narration_source"]["available"] is False


@pytest.mark.parametrize("bound", [False, True])
def test_item_chain_uses_selected_occurrences_despite_repeated_words(bound):
    from backend.engine.narrated_items.evidence import Catalog, bind
    from backend.engine.narrated_items.independent_state import unpack
    from backend.engine.narrated_items.schema import SharedItemExtraction
    from backend.engine.visual_novel.continuity import PLAYER
    from tests.test_narrated_item_transitions import chain
    from tests.test_narrated_items import fixtures, run

    actors, snapshot = fixtures()
    actions = chain()
    text = " ".join(action.evidence for action in actions)
    text += " They later recall: " + text
    if bound:
        catalog = Catalog(text, scope="chain")
        references = list(catalog.narration_passages)
        proposals = [
            action.model_copy(update={"evidence": references[index]})
            for index, action in enumerate(actions)
        ]
        result = bind(SharedItemExtraction(actions=proposals), text, catalog=catalog)
        extraction, failures, _, _ = unpack(result, actors)
        assert not failures
        actions = extraction.actions
    changed, accepted, errors = run(actions, actors, snapshot, narration=text)
    if bound:
        assert not errors and len(accepted) == 2
        assert changed[PLAYER]["inventory"] == [snapshot.items["SHIRT"]]
        assert [row["evidence_span"]["start"] for row in accepted] == [
            0,
            len(chain()[0].evidence) + 1,
        ]
    else:
        assert errors and not accepted and changed == actors


def test_canonical_span_rejects_wrong_position_even_when_quote_exists_elsewhere():
    from backend.core.text_evidence import EvidenceSpan, require_span

    text = "A lamp glows. A bell rings."
    with pytest.raises(ValueError, match="original source occurrence"):
        require_span(text, "A bell rings.", EvidenceSpan(start=0, end=len("A bell rings.")))


@pytest.mark.parametrize(
    "text,room,quote",
    [("ha ha ha", "", "ha ha"), ("The lamp glows.", "The lamp glows.", "The lamp glows.")],
)
def test_legacy_literal_does_not_guess_an_ambiguous_occurrence(text, room, quote):
    from backend.engine.narrated_items.evidence import Catalog, bind
    from backend.engine.narrated_items.schema import SharedItemExtraction
    from tests.test_scene_source_references import proposal

    catalog = Catalog(text, room, scope="ambiguous-literal")
    with pytest.raises(ValueError, match="Ambiguous"):
        catalog.literal(quote, allow_room=True)
    bound = bind(
        SharedItemExtraction(scene_updates=[proposal(quote, source="narration")]),
        text,
        catalog=catalog,
    )
    assert bound.scene_updates[0]["evidence"] is None
