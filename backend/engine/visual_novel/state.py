"""Copy-on-write persistence; only an explicit public projection may leave the server."""

import hashlib
from typing import Any

from pydantic import ValidationError

from backend.engine.visual_novel.schema import (
    MAX_CAST,
    MAX_FINGERPRINTS,
    MAX_MEMORY,
    MAX_PROCESSED,
    STATE_KEY,
    CharacterState,
    SocialMemory,
    SocialProposal,
    SocialState,
)

PROMOTION_EVENTS = 3
POSITIVE_COOLDOWN = 3
# Scores are private narrative guidance, never player knowledge or permission.
EVENT_DELTAS = {
    "support": {"trust": 2, "affinity": 1},
    "cooperation": {"respect": 2, "trust": 1},
    "boundary_respected": {"trust": 2, "tension": -1},
    "boundary_violated": {"trust": -2, "tension": 3},
    "betrayal": {"trust": -3, "affinity": -2, "tension": 3},
    "conflict": {"tension": 2},
}
POSITIVE_EVENTS = {"support", "cooperation", "boundary_respected"}


def load_state(state: Any) -> SocialState | None:
    """None means unsupported/corrupt stored data: preserve it, do not silently reset."""
    raw = (state.entity_states or {}).get(STATE_KEY)
    if raw is None:
        return SocialState()
    try:
        return SocialState.model_validate(raw)
    except (ValidationError, TypeError):
        return None


def save_state(state: Any, social: SocialState) -> None:
    validated = SocialState.model_validate(social.model_dump())
    state.entity_states = {
        **(state.entity_states or {}),
        STATE_KEY: validated.model_dump(mode="json"),
    }


def character_state(npc: Any) -> CharacterState:
    goal = str(getattr(npc, "goal", "") or "").strip()[:1000]
    return CharacterState(
        core=str(getattr(npc, "character", "") or "")[:1000], goals=[goal] if goal else []
    )


def ensure_character(social: SocialState, npc: Any) -> CharacterState | None:
    if npc.id in social.characters:
        character = social.characters[npc.id]
        authored = character_state(npc)
        if not character.core and authored.core:
            character.core = authored.core
        if not character.goals and authored.goals:
            character.goals = authored.goals
        return character
    if len(social.characters) >= MAX_CAST:
        return None
    character = character_state(npc)
    social.characters[npc.id] = character
    return character


def mark_processed(social: SocialState, message_id: str) -> None:
    social.turn += 1
    social.processed_message_ids = (social.processed_message_ids + [message_id])[-MAX_PROCESSED:]


def apply_event(
    social: SocialState, character: CharacterState, proposal: SocialProposal, source_message_id: str
) -> bool:
    """The caller must validate identity, quote provenance and current physical presence."""
    if proposal.source != "scene_context" or proposal.basis != "performed_interaction":
        return False
    if proposal.event not in EVENT_DELTAS or not source_message_id:
        return False
    fingerprint = hashlib.sha256(proposal.evidence.casefold().encode()).hexdigest()
    if (
        source_message_id == character.last_source_message_id
        or any(memory.source_message_id == source_message_id for memory in character.memories)
        or fingerprint in character.fingerprints
    ):
        return False
    if (
        proposal.event in POSITIVE_EVENTS
        and social.turn - character.last_positive_turn < POSITIVE_COOLDOWN
    ):
        return False
    _change_scores(character, proposal, social.turn)
    event_id = social_event_id(source_message_id, proposal.npc_id, proposal.event)
    memory = SocialMemory(
        event_id=event_id,
        source_message_id=source_message_id,
        kind=proposal.event,
        evidence=proposal.evidence,
    )
    character.memories = (character.memories + [memory])[-MAX_MEMORY:]
    character.fingerprints = (character.fingerprints + [fingerprint])[-MAX_FINGERPRINTS:]
    character.last_source_message_id = source_message_id
    character.meaningful_events = min(1000, character.meaningful_events + 1)
    return True


def social_event_id(source_message_id: str, npc_id: str, kind: str) -> str:
    return hashlib.sha256(f"{source_message_id}:{npc_id}:{kind}".encode()).hexdigest()


def _change_scores(character: CharacterState, proposal: SocialProposal, turn: int) -> None:
    for field, delta in EVENT_DELTAS[proposal.event].items():
        minimum = 0 if field == "tension" else -100
        old = getattr(character.relationship, field)
        setattr(character.relationship, field, max(minimum, min(100, old + delta)))
    if proposal.event in POSITIVE_EVENTS:
        character.last_positive_turn = turn


def public_profile(state: Any, npc_id: str) -> dict[str, Any]:
    """Importance is a UI classification, not a revelation of feelings, goals or memory."""
    social = load_state(state)
    character = social.characters.get(npc_id) if social else None
    pinned = bool(character and character.pinned)
    important = bool(character and (pinned or character.meaningful_events >= PROMOTION_EVENTS))
    return {"npc_id": npc_id, "importance": "hero" if important else "supporting", "pinned": pinned}


def set_pinned(state: Any, npc: Any, pinned: bool) -> bool:
    social = load_state(state)
    if social is None:
        return False
    character = ensure_character(social, npc)
    if character is None:
        return False
    character.pinned = pinned
    save_state(state, social)
    return True
