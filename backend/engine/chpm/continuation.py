"""Visible RP degradation preserves confirmed psychology and records continuity gaps."""

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from backend.engine.chpm import experience, host_adapter, host_observations
from backend.engine.chpm.core.contracts import Experience
from backend.engine.chpm.core.history import events
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryState, SimplifiedReply
from backend.engine.chpm.schema import KernelState, Settings, Usage
from backend.engine.chpm.state import KEY, save
from backend.engine.chpm.version import VERSION

if TYPE_CHECKING:
    from backend.engine.chpm.host_state import Mind
    from backend.engine.chpm.runtime import Turn

COOLDOWN_TURNS = 3

INSTRUCTION = """Continue this RP turn using ordinary character narration.
NPC analysis is temporarily unavailable. Use the pinned identities, current host
facts and established conversation. Give a relevant response to the player's action;
do not fill the turn with unchanged scenery, a technical apology or permission to
keep writing. Preserve each NPC's own motives, values, voice and player agency.
Earlier intentions and feelings may have changed during unreviewed turns. Do not
present old psychological estimates as current facts or invent shared history.
The recovery marker is private host data, never prose to repeat. Content policy
and the story's existing tone remain unchanged.
"""


def enabled(turn: "Turn") -> bool:
    settings = turn.initial.settings
    return settings.mode == "live" and settings.failure_policy == "continue"


def identities(manager: Any, state: KernelState, actors: list[Any]) -> dict:
    names = {actor.id: str(actor.name) for actor in actors}
    result = {}
    for actor in actors:
        mind = state.minds.get(actor.id)
        if mind and (
            mind.genesis.scope.world_id != manager.game_id
            or mind.genesis.scope.observer_id != actor.id
        ):
            raise ChpmError("CHPM fallback identity belongs to another session or NPC.")
        profile = (
            host_adapter.narrative_identity(mind)
            if mind
            else {
                "character": str(getattr(actor, "character", "") or ""),
                "goal": str(getattr(actor, "goal", "") or ""),
                "personality": (getattr(actor, "metadata_json", None) or {}).get(
                    "personality_profile", {}
                ),
            }
        )
        result[actor.id] = {
            "name": actor.name,
            "authored_identity": profile,
            "current_host_state": host_observations.capture(
                manager.state, actor, names
            ).model_dump(),
        }
    return result


def activate(turn: "Turn", reason: str, issues: list[str] | None = None) -> None:
    turn.simplified = True
    turn.usage.simplified = True
    turn.usage.fallback_reason = reason
    turn.usage.status = "failed"
    turn.usage.detail = "NPC analysis paused; RP continued with the last confirmed identity."
    turn.fallback_issues = (issues or [])[:8]
    # All proposed psychological updates remain turn-local and are abandoned together.
    turn.decisions = {}
    turn.minds = {}
    turn.memories = {}
    turn.agendas = {}
    turn.verdict = None
    turn.deferred_names = {}


def contract(turn: "Turn") -> str:
    return INSTRUCTION + json.dumps(
        {"npc_identities": turn.fallback_identities, "continuity_gap": gap_context(turn.initial)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def gap_context(state: KernelState) -> dict:
    return {
        "unreviewed_turns": state.recovery.pending_gap_turns,
        "total_unreviewed_turns": state.recovery.total_simplified_turns,
        "meaning": "Unreviewed dialogue remains in story history, not confirmed psychology; current host observations take precedence.",
    }


def previous(state: KernelState, actor_id: str) -> Any:
    if (
        state.recovery.last_gap_revision
        and state.last_active.get(actor_id, 0) <= state.recovery.last_gap_revision
    ):
        return None
    return state.actors.get(actor_id)


def experience_view(mind: "Mind", cursors: dict[str, int]) -> dict:
    result = experience.view(mind)
    cutoff = cursors.get(mind.genesis.scope.observer_id)
    if cutoff is None:
        return result
    before_gap = {
        event.payload.record_id
        for event in events(mind.snapshot)
        if isinstance(event.payload, Experience) and event.sequence <= cutoff
    }
    for row in result["states"]:
        if row["record_id"] in before_gap:
            row["status"] = "historical_current_unknown"
    return result


def rebase_gap(turn: "Turn", actor_id: str) -> None:
    cutoff = turn.gap_cursors.get(actor_id)
    original = turn.initial.minds.get(actor_id)
    if cutoff is None or original is None:
        return
    prior_ids = {event.event_id for event in events(original.snapshot) if event.sequence <= cutoff}
    # A retracted source can reuse sequence numbers for new observations. Keep
    # the cutoff on the retained old prefix, never on newly appraised feelings.
    turn.gap_cursors[actor_id] = max(
        (
            event.sequence
            for event in events(turn.minds[actor_id].snapshot)
            if event.event_id in prior_ids
        ),
        default=0,
    )


def finish(manager: Any, turn: "Turn", reply: Any) -> None:
    if not turn.simplified_text or not reply.content.strip():
        raise ChpmError("No ordinary RP continuation is ready to commit.")
    if reply.content != turn.simplified_text:
        raise ChpmError("The ordinary RP continuation changed before commit.")
    if reply.session_id != manager.game_id or reply.role != "assistant":
        raise ChpmError("CHPM simplified reply belongs to another session or role.")
    result = turn.initial.model_copy(deep=True)
    result.usage = turn.usage
    recovery = result.recovery
    if turn.usage.fallback_reason == "cooldown":
        recovery.cooldown_remaining = max(0, recovery.cooldown_remaining - 1)
    else:
        recovery.consecutive_failures += 1
        if recovery.consecutive_failures >= 2:
            recovery.cooldown_remaining = COOLDOWN_TURNS
    recovery.pending_gap_turns += 1
    recovery.total_simplified_turns += 1
    recovery.last_gap_revision = turn.initial.revision + 1
    recovery.gap_cursors.update(
        {
            actor: result.minds[actor].snapshot.cursor
            for actor in turn.fallback_identities
            if actor in result.minds
        }
    )
    record = SimplifiedReply(
        input_id=turn.input_id,
        reply_id=reply.id,
        reply_revision=reply.revision_id,
        reply_hash=digest(reply.content),
        reason=turn.usage.fallback_reason,
        actor_ids=list(turn.fallback_identities),
    )
    recovery.recent = [*recovery.recent, record][-8:]
    save(manager.state, result, expected_revision=turn.initial.revision)


def mark_verified(state: KernelState) -> None:
    state.recovery.consecutive_failures = 0
    state.recovery.cooldown_remaining = 0
    state.recovery.pending_gap_turns = 0


class StatusProjection(BaseModel):
    """Read only public metadata; turn admission still validates the complete mind."""

    settings: Settings = Field(default_factory=Settings)
    usage: Usage = Field(default_factory=Usage)
    recovery: RecoveryState = Field(default_factory=RecoveryState)


def snapshot_status(state: Any) -> dict:
    raw = (getattr(state, "entity_states", None) or {}).get(KEY) or {}
    return public_status(StatusProjection.model_validate(raw))


def public_status(state: KernelState | StatusProjection) -> dict:
    return {
        "module_version": VERSION,
        "mode": state.settings.mode,
        "quality": "simplified"
        if state.usage.simplified
        else "verified"
        if state.usage.status == "validated"
        else "idle",
        "reason": state.usage.fallback_reason,
        "cooldown_remaining": state.recovery.cooldown_remaining,
        "unreviewed_turns": state.recovery.pending_gap_turns,
        "total_simplified_turns": state.recovery.total_simplified_turns,
    }
