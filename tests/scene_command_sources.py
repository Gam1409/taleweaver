"""Typed, input-bound external sources for pure staging owner tests."""

from hashlib import sha256
from types import SimpleNamespace

from backend.core.text_passages import spans
from backend.engine import turn_controls
from backend.engine.scene_staging.attribution import Scope
from backend.engine.scene_staging.schema import SceneDelta, StagingCause
from backend.engine.visual_novel.movement_sources import Source

MOVE_INPUT = "I guide NPC near Other while NPC stays on all fours."
MOVE_EVIDENCE = "The player guides NPC near Other while NPC stays on all fours."
MOVE_TEXT = MOVE_EVIDENCE + " Other sits."
STAND_INPUT = "I help NPC stand up."
STAND_TEXT = "The player helps NPC stand up."
CLEAR_INPUT = "I guide NPC away from the avatar while NPC stays on all fours."
CLEAR_TEXT = "The player guides NPC away from the avatar while NPC stays on all fours."


def bind_player_source(host, text, *, input_id="input"):
    turn_controls.begin(host)
    message = SimpleNamespace(id=input_id, revision_id=f"{input_id}-revision", content=text)
    host._vn_player_message_id = input_id
    turn_controls.bind_input(host, message)
    source = Source(
        message_id=input_id,
        revision_id=message.revision_id,
        content_hash=sha256(text.encode()).hexdigest(),
        scene_id=host.state.current_scene_id,
        role="user",
        text=text,
        passages={f"player:{key}": value for key, value in spans(text).items()},
    )
    host._vn_movement_sources = {"current_player_action": source}
    return source


def player_authority(host):
    source = host._vn_movement_sources["current_player_action"]
    control = turn_controls.scope(host, "scene_staging")
    assert (source.message_id, source.revision_id, source.content_hash) == (
        control["input_id"],
        control["input_revision"],
        control["input_hash"],
    )
    return Scope(control, host.state.current_scene_id, frozenset({"npc"}), source, ())


def external_change(host, narration, *, evidence=None, **fields):
    source = host._vn_movement_sources["current_player_action"]
    quote = evidence or narration
    start = narration.index(quote)
    return SceneDelta(
        entity_id="npc",
        performer_id="__player__",
        cause=StagingCause(
            kind="current_player_action",
            basis="resolved_external_effect",
            passage_id=next(iter(source.passages)),
        ),
        evidence=quote,
        evidence_span={"start": start, "end": start + len(quote)},
        **fields,
    ).model_dump()
