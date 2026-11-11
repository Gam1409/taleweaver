"""Allowlisted host observations and pinned identity for the live dialogue pilot."""

from types import SimpleNamespace
from typing import Any

from backend.engine.chpm import (
    host_observations,
    host_scene,
    host_sources,
    identity_adapter,
    observation_sources,
)
from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, Source, record_many
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
    # Causal recall already checked this exact observer during the same preparation.
    checked = getattr(turn, "reconciled_minds", {}).get(actor.id)
    mind = checked if checked is not None else await host_sources.reconcile(manager, mind)
    facts = host_scene.capture(manager, actor, turn.present_names)
    change = host_observations.difference(host_observations.previous(mind), facts)
    anchor = {
        "message_id": observed.message_id,
        "revision_id": observed.revision_id,
        "content_hash": observed.content_hash,
        "role": "user",
    }
    catchup = getattr(turn, "catchup", None)
    additions = [
        *(catchup.accepted.get(actor.id, []) if catchup is not None else []),
        Source(
            **anchor,
            speaker_id=actor.id,
            kind="host_frame",
            text=host_observations.frame(facts),
            facts=facts,
        ),
    ]
    if change:
        additions.append(Source(**anchor, speaker_id=actor.id, kind="world_event", text=change))
    additions.extend(
        Source(**anchor, speaker_id="@player", kind="speech", text=quote)
        for quote in turn.perceptions[actor.id].quotes
    )
    additions.extend(observation_sources.additions(mind, facts, anchor))
    return record_many(mind, additions, minute=observed.minute)


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
    return {
        "current_host_observations": [item.model_dump() for item in frames[-1:]],
        "belief_context_ref": "appraisal_context.existing_beliefs",
    }


def add_context(supplied: dict, mind: Mind) -> None:
    supplied["psychological_state"] = context(mind)
    facts = host_observations.previous(mind)
    if facts is not None and facts.physical_conditions is not None:
        # The citable current frame already carries these facts and its omissions.
        # Keep the standalone warning if the physical ledger is unavailable.
        supplied.pop("own_physical_conditions", None)


def narrative_identity(mind: Mind) -> dict:
    actor = actor_view(SimpleNamespace(id=mind.genesis.scope.observer_id, name=""), mind)
    return {
        "character": actor.character,
        "goal": actor.goal,
        "personality": personality_context(actor),
    }


def finish(turn: Any, reply: Any, additions: list[Any], actor_id: str, *, minute: int) -> Mind:
    from backend.engine.chpm import reports

    mind: Mind = turn.minds[actor_id]
    sources = []
    for entry in additions:
        # Player observations were already ingested at prepare. Only reviewed speech
        # is added here; narration never becomes a witnessed world outcome.
        if entry.source_role != "assistant":
            continue
        if entry.source_message_id != reply.id or entry.quote not in reply.content:
            raise ChpmError("CHPM speech source differs from the completed reply.")
        sources.append(
            Source(
                message_id=entry.source_message_id,
                revision_id=entry.source_revision_id,
                content_hash=entry.source_hash,
                role="assistant",
                speaker_id=entry.speaker_id,
                kind="speech",
                text=entry.quote,
                report=reports.lineage(turn, actor_id, entry),
            )
        )
    return record_many(mind, sources, minute=minute)
