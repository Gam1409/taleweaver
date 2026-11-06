"""Exercise production cognitive ports, scheduling and reviewed commits without a game DB."""

import json
from types import SimpleNamespace
from typing import Any

from backend.engine.chpm import (
    cognition,
    context,
    host_adapter,
    host_observations,
    perception,
    rendering,
    roster,
    runtime,
)
from backend.engine.chpm.evaluation.matrix_cases import MatrixCase, actors
from backend.engine.chpm.evaluation.matrix_history import seed
from backend.engine.chpm.evaluation.port import MeasuredFactory
from backend.engine.chpm.evaluation.runner import BASELINE
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import KernelState, Observation, Settings
from backend.engine.chpm.state import KEY, load


async def run(
    case: MatrixCase,
    factory: Any,
    *,
    all_present: bool = False,
    timeout: float = 120,
    max_output_tokens: int | None = None,
    agent_steps: int = 0,
    max_input_chars: int | None = None,
) -> dict:
    cast = actors(case)
    active = case.population if all_present else case.active
    settings = Settings(
        failure_policy="strict",
        mode="live",
        actor_ids=[a.id for a in cast],
        max_active_npcs=active,
        agent_steps=agent_steps,
        max_calls_per_turn=active * (1 + agent_steps) + 5,
        max_input_chars=max_input_chars
        if max_input_chars is not None
        else (96000 if active > 3 else 24000),
        max_output_tokens=max_output_tokens
        if max_output_tokens is not None
        else (8192 if case.population > 3 else 2048),
    )
    session = "matrix-" + case.id
    before = KernelState(settings=settings, minds={a.id: seed(case, a, session) for a in cast})
    measured = MeasuredFactory(factory, limit=active * (1 + agent_steps) + 6, timeout=timeout)
    minute = case.history_turns * (1440 if case.daily else 2) + 1
    host = SimpleNamespace(
        game_id=session,
        user=None,
        _chpm_model_factory=measured,
        state=SimpleNamespace(
            entity_states={KEY: before.model_dump()}, in_game_time=minute, current_scene_id="scene"
        ),
    )
    turn = runtime.Turn(before, "input", present_names={a.id: a.name for a in cast})
    host._chpm_turn = turn
    result: dict = {"case": case.id, "status": "failed", "error": "", "response": ""}
    try:
        turn.perceptions = await perception.project(
            host, settings, turn.usage, case.message, turn.present_names
        )
        selected = roster.select(before, turn.perceptions)
        turn.deferred_names = {a.id: a.name for a in cast if a.id not in selected}
        turn.names = {a.id: a.name for a in cast if a.id in selected}
        for actor in cast:
            if actor.id in selected:
                await _think(host, turn, case, actor, minute)
        result["response"] = await _speak(host, turn, case, measured)
        result["status"] = "ok"
    except Exception as exc:
        result["error"] = (
            str(exc) if isinstance(exc, (ChpmError, ValueError)) else type(exc).__name__
        )
    after = load(host.state)
    result.update(
        calls=[call.model_dump() for call in measured.calls],
        usage=turn.usage.model_dump(),
        perceptions={key: value.model_dump() for key, value in turn.perceptions.items()},
        active=list(turn.decisions),
        inactive=list(turn.deferred_names),
        identity_unchanged=all(
            after.minds[key].genesis == mind.genesis for key, mind in before.minds.items()
        ),
        failed_turn_unchanged=result["status"] == "ok" or after == before,
        inactive_unchanged=all(
            after.minds[key] == before.minds[key] for key in turn.deferred_names
        ),
        decisions={key: value.model_dump() for key, value in turn.decisions.items()},
        state_changes={
            key: {
                "before_cursor": before.minds[key].snapshot.cursor,
                "after_cursor": value.snapshot.cursor,
                "beliefs": [b.model_dump() for b in value.snapshot.beliefs],
                "experiences": [e.model_dump() for e in value.snapshot.experiences],
            }
            for key, value in after.minds.items()
        },
        candidate_distinctness=_distinctness(turn),
        psychological_quality="unrated; technical success is not psychological validity",
    )
    return result


async def _think(host: Any, turn: runtime.Turn, case: MatrixCase, actor: Any, minute: int) -> None:
    heard = turn.perceptions[actor.id]
    observed = Observation(
        session_id=host.game_id,
        message_id="input",
        content_hash=digest(case.message),
        sequence=case.history_turns + 1,
        turn_revision=1,
        scene_id="scene",
        minute=minute,
        player_request="\n".join(heard.quotes),
        perception_uncertain=heard.uncertain,
        perception_kinds=heard.quote_kinds,
    )
    pending = turn.initial.minds[actor.id]
    facts = HostFacts(
        scene_id="scene", visible_actor_ids=tuple(k for k in turn.present_names if k != actor.id)
    )
    frame = host_observations.frame(facts)
    anchor: dict[str, Any] = dict(
        message_id="input", content_hash=observed.content_hash, role="user"
    )
    change = host_observations.difference(host_observations.previous(pending), facts)
    change = "\n".join(part for part in (change, case.observed_event) if part)
    pending = record(
        pending,
        Source(**anchor, speaker_id=actor.id, kind="host_frame", text=frame, facts=facts),
        minute=minute,
    )
    if change:
        pending = record(
            pending,
            Source(**anchor, speaker_id=actor.id, kind="world_event", text=change),
            minute=minute,
        )
    for quote in heard.quotes:
        pending = record(
            pending,
            Source(**anchor, speaker_id="@player", kind="speech", text=quote),
            minute=minute,
        )
    supplied = await context.actor_context(host, host_adapter.actor_view(actor, pending), None)
    supplied.update(
        observation=observed.model_dump(),
        psychological_state=host_adapter.context(pending),
        declared_agenda_not_world_facts=[],
        agenda_creation_available=False,
    )
    turn.decisions[actor.id], turn.minds[actor.id] = await cognition.deliberate(
        host, turn.initial.settings, turn.usage, actor.id, observed, supplied, [], pending
    )
    turn.decisions[actor.id].perception_audit = heard.coverage


async def _speak(host: Any, turn: runtime.Turn, case: MatrixCase, factory: MeasuredFactory) -> str:
    rendering.preflight(turn)
    system = BASELINE + "\n" + runtime.contract(turn)
    content = json.dumps(
        {"language": "English", "scene": case.scene, "player_message_untrusted": case.message}
    )
    if len(system) + len(content) > turn.initial.settings.max_input_chars:
        raise ChpmError("Matrix narrator context exceeds its configured budget.")
    model = factory("complex")
    model.max_tokens = min(model.max_tokens, 4096)
    text = await model.aexecute_simple_task(
        system, content, model.model, operation="chpm_evaluation", phase="narration"
    )
    text = await rendering.validate(
        host, text, completed=True, resolution=case.scene, system_prompt=BASELINE + content
    )
    reply = SimpleNamespace(
        id="reply",
        session_id=host.game_id,
        role="assistant",
        content=text,
        revision_id=None,
        scene_id="scene",
    )
    runtime.finish(host, reply, completed=True)
    return text


def _distinctness(turn: runtime.Turn) -> dict:
    result = {}
    for actor, decision in turn.decisions.items():
        texts = [
            " ".join(candidate.intention.casefold().split())
            for candidate in decision.proposal.candidates
        ]
        result[actor] = {
            "exact_duplicate_intents": len(texts) - len(set(texts)),
            "semantic_distinctness": "manual review required",
        }
    return result
