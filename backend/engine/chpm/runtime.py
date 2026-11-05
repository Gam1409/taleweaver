"""Turn-local preparation; accepted decisions are persisted with the completed reply."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.core.game_modes import is_vn
from backend.engine.chpm import context, inference, prompts
from backend.engine.chpm.kernel import ChpmError, digest, existing, fingerprint, select
from backend.engine.chpm.schema import Decision, KernelState, Proposal, Usage, Verdict
from backend.engine.chpm.state import load, save
from backend.engine.turn_replay.transactions import release_for_model

logger = logging.getLogger(__name__)


@dataclass
class Turn:
    initial: KernelState
    input_id: str
    decisions: dict[str, Decision] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    verdict: Verdict | None = None
    names: dict[str, str] = field(default_factory=dict)


def current(manager: Any) -> Turn | None:
    value = getattr(manager, "_chpm_turn", None)
    return value if isinstance(value, Turn) else None


def buffered(manager: Any) -> bool:
    turn = current(manager)
    return bool(turn and turn.initial.settings.mode == "live" and turn.decisions)


def contract(turn: Turn) -> str:
    data = {
        actor: {"name": turn.names.get(actor, actor), **decision.selected.model_dump()}
        for actor, decision in turn.decisions.items()
    }
    return prompts.NARRATE + json.dumps(data, ensure_ascii=False)


async def prepare(manager: Any, message: str, actors: list[Any]) -> str:
    state = load(manager.state)
    if state.settings.mode == "off" or not is_vn(manager.adventure):
        return ""
    input_id = getattr(manager, "_vn_player_message_id", None)
    if not input_id:
        return ""
    old = current(manager)
    if old is not None and old.input_id == input_id:
        return contract(old) if buffered(manager) else ""
    turn = Turn(state, input_id)
    manager._chpm_turn = turn
    selected = [
        actor
        for actor in actors
        if actor.id in state.settings.actor_ids and context.available(actor, manager.state)
    ]
    if not selected:
        return ""
    try:
        await _prepare(manager, turn, message, selected)
    except Exception as exc:
        turn.usage.status = "failed"
        turn.usage.detail = str(exc) if isinstance(exc, ChpmError) else type(exc).__name__
        logger.warning(
            "CHPM preparation failed: session=%s error=%s", manager.game_id, type(exc).__name__
        )
        if state.settings.mode == "live":
            raise ChpmError("CHPM could not prepare this turn. " + turn.usage.detail) from exc
        turn.decisions = {}
        return ""
    turn.usage.status = "prepared" if state.settings.mode == "live" else "shadow"
    manager._chpm_publish_after_commit = buffered(manager)
    return contract(turn) if buffered(manager) else ""


async def _prepare(manager: Any, turn: Turn, message: str, actors: list[Any]) -> None:
    if not (
        getattr(manager, "_turn_replay_recorded", False) or getattr(manager, "_replaying", False)
    ):
        raise ChpmError("CHPM needs a recoverable turn snapshot.")
    observed = await context.observation(manager, message)
    await release_for_model(manager)
    for actor in sorted(actors, key=lambda item: item.id):
        turn.names[actor.id] = str(actor.name)
        previous = turn.initial.actors.get(actor.id)
        supplied = await context.actor_context(manager, actor, previous)
        supplied["observation"] = observed.model_dump()
        key = fingerprint(supplied)
        decision = existing(previous, observed, key)
        if decision is None:
            proposal = await inference.request(
                manager,
                turn.initial.settings,
                turn.usage,
                prompts.PROPOSE,
                supplied,
                Proposal,
                "proposal",
            )
            decision = select(
                actor.id, observed, proposal, goal=supplied["authored_goal"], context_hash=key
            )
        turn.decisions[actor.id] = decision


def finish(manager: Any, reply: Any, *, completed: bool) -> None:
    turn = current(manager)
    if turn is None or not completed:
        return
    result = turn.initial.model_copy(deep=True)
    result.usage = turn.usage
    for actor, decision in turn.decisions.items():
        _finish_decision(turn, decision, reply)
        result.actors[actor] = decision
    save(manager.state, result, expected_revision=turn.initial.revision)
    manager._chpm_turn = None


def _finish_decision(turn: Turn, decision: Decision, reply: Any) -> None:
    if turn.initial.settings.mode == "shadow":
        decision.status = "shadow"
        return
    if turn.verdict is None or not turn.verdict.matches:
        raise ChpmError("CHPM cannot commit a reply without successful validation.")
    decision.status = "delivered"
    decision.reply_id = reply.id
    decision.reply_revision = reply.revision_id
    decision.reply_hash = digest(reply.content)
    decision.spoken_evidence = next(
        evidence.quote
        for evidence in turn.verdict.evidence
        if evidence.actor_id == decision.actor_id
    )
