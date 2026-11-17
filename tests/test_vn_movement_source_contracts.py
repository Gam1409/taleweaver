"""Source preparation and physical batches retain their exact bounded contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.mutation_targets import TargetIndex
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.engine.visual_novel.movement_recovery import _resolve_actor
from backend.engine.visual_novel.movement_sources import MAX_PASSAGES, MAX_SOURCE_CHARS, _source


def message(text):
    return SimpleNamespace(
        id="reply",
        session_id="session",
        revision_id="revision",
        role="assistant",
        content=text,
        scene_id="START",
        is_debug=False,
        npc_journal=None,
        npc_recovery=None,
    )


@pytest.mark.parametrize("count", [MAX_PASSAGES, MAX_PASSAGES + 1])
def test_only_supplied_bounded_passages_are_available_for_source_resolution(count):
    selected = _source(message(" ".join(["A sentence."] * count)), "history")
    assert len(selected.passages) == MAX_PASSAGES
    assert all(key.startswith("history:p") for key in selected.passages)
    assert all(selected.text[row.start : row.end] == row.text for row in selected.passages.values())


@pytest.mark.parametrize("extra", [0, 1])
def test_source_character_bound_keeps_whole_exact_passages(extra):
    sentence = "x" * 499 + "."
    text = " ".join([sentence] * 7 + ["x" * (499 + extra) + "."])
    selected = _source(message(text), "player")
    used = sum(len(row.text) for row in selected.passages.values())
    assert used <= MAX_SOURCE_CHARS
    assert len(selected.passages) == (8 if extra == 0 else 7)


@pytest.mark.parametrize("batch_size", [8, 9])
async def test_recovery_cannot_expand_the_existing_eight_actor_movement_limit(batch_size):
    reply = message("Lina leaves through the door into the annex.")
    manager = SimpleNamespace(
        db=SimpleNamespace(get=AsyncMock(return_value=reply)),
        game_id="session",
        state=SimpleNamespace(entity_states={}),
        _vn_movement_sources={"previous_narration": _source(reply, "history")},
        _vn_player_message_id="player",
        _vn_movement_input="player",
        _vn_story_beat=None,
    )
    proposal = VNProgressionIntent.model_validate(
        {
            "moved_entities": [
                {
                    "entity_id": "LINA",
                    "to_scene_id": "ANNEX",
                    "movement_source": {
                        "kind": "previous_narration",
                        "passage_id": "history:p0",
                        "basis": "completed",
                    },
                }
            ]
        }
    )
    event = GameEvent(moved_entities=proposal.moved_entities)
    before = {
        "scene_id": "START",
        "actors": {"LINA": {"can_move": True, "allowed_destinations": ["ANNEX"]}},
    }
    arguments = (
        manager,
        event,
        "LINA",
        event.moved_entities,
        [],
        (proposal.moved_entities, []),
        before,
        TargetIndex([{"id": "ANNEX"}]),
        batch_size,
    )
    if batch_size == 9:
        with pytest.raises(ValueError, match="Too many"):
            await _resolve_actor(*arguments)
        return
    await _resolve_actor(*arguments)
