"""Allowlisted host observations and pinned identity for the live dialogue pilot."""

from types import SimpleNamespace
from typing import Any

from backend.engine.chpm import host_observations, host_sources, identity_adapter
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, Source, record
from backend.engine.chpm.kernel import ChpmError
from backend.engine.personality.profile import personality_context


async def prepare(manager: Any, turn: Any, actor: Any, observed: Any) -> Mind:
    if (
        observed.session_id != manager.game_id
        or observed.scene_id != manager.state.current_scene_id
    ):
        raise ChpmError("CHPM observation does not match the active host session and scene.")
    scope = Scope(world_id=manager.game_id, branch_id="session-main-v1", observer_id=actor.id)
    mind = turn.initial.minds.get(actor.id)
    if mind is None:
        if len(turn.initial.minds) + len(set(turn.minds) - set(turn.initial.minds)) >= 32:
            raise ChpmError("CHPM identity archive is full; no characters were discarded.")
        genesis = Genesis(
            scope=scope, identity=identity_adapter.from_actor(actor), sim_minute=observed.minute
        )
        mind = Mind(genesis=genesis, snapshot=initial(genesis))
    if mind.genesis.scope != scope:
        raise ChpmError("CHPM psychological state belongs to another session or NPC.")
    mind = await host_sources.reconcile(manager, mind)
    facts = host_observations.capture(manager.state, actor, turn.present_names)
    change = host_observations.difference(host_observations.previous(mind), facts)
    anchor = {
        "message_id": observed.message_id,
        "revision_id": observed.revision_id,
        "content_hash": observed.content_hash,
        "role": "user",
    }
    mind = record(
        mind,
        Source(
            **anchor,
            speaker_id=actor.id,
            kind="host_frame",
            text=host_observations.frame(facts),
            facts=facts,
        ),
        minute=observed.minute,
    )
    if change:
        mind = record(
            mind,
            Source(**anchor, speaker_id=actor.id, kind="world_event", text=change),
            minute=observed.minute,
        )
    for quote in turn.perceptions[actor.id].quotes:
        mind = record(
            mind,
            Source(**anchor, speaker_id="@player", kind="speech", text=quote),
            minute=observed.minute,
        )
    return mind


def actor_view(actor: Any, mind: Mind) -> Any:
    identity = mind.genesis.identity
    return SimpleNamespace(
        id=actor.id,
        name=actor.name,
        character=identity.description,
        goal="\n".join(identity.authored_goals),
        metadata_json={
            "personality_profile": {trait.key: trait.value for trait in identity.traits}
        },
    )


def context(mind: Mind) -> dict:
    frames = [
        entry
        for entry in mind.snapshot.evidence
        if entry.event_id in mind.sources and mind.sources[entry.event_id].kind == "host_frame"
    ]
    beliefs = relationships.recent(mind.snapshot)
    return {
        "current_host_observations": [item.model_dump() for item in frames[-1:]],
        "subjective_beliefs_not_world_facts": [item.model_dump() for item in beliefs],
        "beliefs_omitted": len(mind.snapshot.beliefs) - len(beliefs),
        "relationship_interpretations": relationships.claims(mind.snapshot, beliefs),
    }


def narrative_identity(mind: Mind) -> dict:
    actor = actor_view(SimpleNamespace(id=mind.genesis.scope.observer_id, name=""), mind)
    return {
        "character": actor.character,
        "goal": actor.goal,
        "personality": personality_context(actor),
    }


def finish(turn: Any, reply: Any, additions: list[Any], actor_id: str, *, minute: int) -> Mind:
    mind: Mind = turn.minds[actor_id]
    for entry in additions:
        # Player observations were already ingested at prepare. Only reviewed speech
        # is added here; narration never becomes a witnessed world outcome.
        if entry.source_role != "assistant":
            continue
        if entry.source_message_id != reply.id or entry.quote not in reply.content:
            raise ChpmError("CHPM speech source differs from the completed reply.")
        mind = record(
            mind,
            Source(
                message_id=entry.source_message_id,
                revision_id=entry.source_revision_id,
                content_hash=entry.source_hash,
                role="assistant",
                speaker_id=entry.speaker_id,
                kind="speech",
                text=entry.quote,
            ),
            minute=minute,
        )
    return mind
