"""Bounded causal continuity extracted by the existing reviewer, never mechanics."""

from typing import Any

from sqlalchemy import select

from backend.engine.chpm import causal_audit, causal_graph, host_sources
from backend.engine.chpm.agent_limits import MAX_PINNED_SOURCES
from backend.engine.chpm.causal_contracts import (
    MAX_CLOSED,
    MAX_OPEN,
    Anchor,
    Fact,
    Memory,
    Thread,
    Update,
)
from backend.engine.chpm.host_state import Mind, Source, identifier
from backend.engine.chpm.kernel import ChpmError, digest, fingerprint
from backend.models.chat import ChatMessage


def anchors(thread: Thread) -> list[Anchor]:
    return [
        thread.origin,
        *(fact.source for fact in thread.facts.values()),
        *([thread.closure] if thread.closure else []),
    ]


def view(threads: list[Thread], mind: Mind | None = None) -> list[dict]:
    """Current facts stay small; exact evidence remains in the session save, not repeated."""
    active = [thread for thread in threads if thread.closure is None]
    recent = [thread for thread in threads if thread.closure is not None][-1:]
    return [
        {
            "id": thread.id,
            "status": "closed" if thread.closure else "open",
            "facts": {key: fact.text for key, fact in thread.facts.items()},
            **({"links": causal_graph.current_links(mind, thread)} if mind else {}),
        }
        for thread in [*active, *recent]
    ]


async def recall(manager: Any, memory: Memory, actors: set[str]) -> dict[str, list[Thread]]:
    owned = {actor: memory.actors.get(actor, []) for actor in actors}
    references = [
        anchor for threads in owned.values() for thread in threads for anchor in anchors(thread)
    ]
    if not references:
        return owned
    rows = await manager.db.scalars(
        select(ChatMessage).where(
            ChatMessage.session_id == manager.game_id,
            ChatMessage.id.in_({ref.message_id for ref in references}),
        )
    )
    messages = {row.id: row for row in rows}
    return {
        actor: [
            thread
            for thread in threads
            if all(
                _valid(ref, messages.get(ref.message_id), manager.game_id)
                for ref in anchors(thread)
            )
        ]
        for actor, threads in owned.items()
    }


def _valid(ref: Anchor, message: Any, session_id: str) -> bool:
    return bool(
        message is not None
        and ref.session_id == session_id == message.session_id
        and message.role == "assistant"
        and ref.revision_id == message.revision_id
        and ref.content_hash == digest(message.content)
        and ref.quote in message.content
    )


async def prepare(manager: Any, turn: Any, actor_ids: set[str]) -> None:
    turn.causal_threads = await recall(manager, turn.initial.causal_memory, actor_ids)
    checked: dict[str, Mind] = {}
    for actor in sorted(actor_ids):
        mind = turn.initial.minds.get(actor)
        if mind and any(source.kind == "causal_state" for source in mind.sources.values()):
            checked[actor] = await host_sources.reconcile(manager, mind)
            turn.causal_threads[actor] = causal_graph.frontier(checked[actor])
    turn.reconciled_minds = checked
    for actor, identity in turn.fallback_identities.items():
        identity["causal_continuity_not_world_facts"] = view(
            turn.causal_threads.get(actor, []), checked.get(actor)
        )


def apply(turn: Any, result: Any, reply: Any, available: dict[str, str]) -> None:
    """Commit only with accepted narration; malformed optional notes never kill an RP turn."""
    if not turn.verdict or not turn.verdict.matches or not turn.decisions:
        return
    if not turn.verdict.causal_updates and not turn.causal_threads:
        return
    if reply.session_id != reply_session(turn) or reply.role != "assistant":
        raise ChpmError("Causal continuity belongs to another session or role.")
    actors = {
        actor: threads
        for actor, threads in {**result.causal_memory.actors, **turn.causal_threads}.items()
        if threads
    }
    seen: set[str] = set()
    for raw in turn.verdict.causal_updates:
        try:
            update = Update.model_validate(raw)
            if update.actor_id not in turn.decisions or update.actor_id in seen:
                raise ValueError("Causal updates require one controlled owner per turn.")
            if update.actor_id not in result.minds:
                raise ValueError("Causal updates require the owner's retained evidence ledger.")
            previous = actors.get(update.actor_id, [])
            changed, thread = _change(previous, update, reply, available)
            if update.actor_id not in actors and len(actors) >= 32:
                raise ValueError("Causal observer archive is full.")
            mind, notes = causal_graph.remember(
                result.minds[update.actor_id], thread, update, reply, available
            )
            changed = causal_graph.frontier(mind)
            result.minds[update.actor_id] = mind
            causal_audit.add(result.usage, notes)
            actors[update.actor_id] = changed
            if update.action == "close" and len(changed) < len(previous):
                causal_audit.add(
                    result.usage,
                    [
                        "Older closed thread left the recent view; its original messages remain in history."
                    ],
                )
            seen.add(update.actor_id)
        except ValueError as exc:
            causal_audit.add(
                result.usage, ["Skipped causal update: " + str(exc).splitlines()[0][:180]]
            )
    result.causal_memory = Memory(actors=actors)


def pins(mind: Mind, threads: list[Thread]) -> dict[str, tuple[str, Source, str]]:
    """Pin causal excerpts by exact provenance, independent of language or lexical RAG hits."""
    if any(thread.actor_id != mind.genesis.scope.observer_id for thread in threads):
        raise ChpmError("Causal evidence belongs to another NPC.")
    by_id = {thread.id: thread for thread in threads}
    active = [by_id[thread["id"]] for thread in view(threads)]
    result: dict[str, tuple[str, Source, str]] = {}
    for field in ("event", "consequence", "cause", "next_step", "purpose"):
        for thread in active:
            if field not in thread.facts or len(result) >= MAX_PINNED_SOURCES:
                continue
            ref = thread.facts[field].source
            source = Source(
                message_id=ref.message_id,
                revision_id=ref.revision_id,
                content_hash=ref.content_hash,
                role="assistant",
                speaker_id=thread.actor_id,
                kind="narration",
                text=ref.quote,
            )
            key = identifier(source, mind.genesis)
            if key in mind.sources:
                result[key] = (key, source, source.text)
    return {f"c{index}": item for index, item in enumerate(result.values(), 1)}


def reply_session(turn: Any) -> str:
    return str(next(iter(turn.decisions.values())).observation.session_id)


def _change(
    threads: list[Thread], update: Update, reply: Any, available: dict[str, str]
) -> tuple[list[Thread], Thread]:
    facts = {
        key: Fact(text=value.text, source=_anchor(reply, available.get(value.passage_id, "")))
        for key, value in update.facts.items()
    }
    target = next(
        (thread for thread in threads if thread.id == update.thread_id and thread.closure is None),
        None,
    )
    if update.action != "open" and target is None:
        raise ValueError("Unknown or closed causal thread.")
    if update.action == "open":
        origin = next(iter(facts.values())).source
        identifier = fingerprint(
            {
                "actor": update.actor_id,
                "origin": origin.model_dump(),
                "purpose": facts["purpose"].text,
            }
        )
        existing = next((thread for thread in threads if thread.id == identifier), None)
        if existing:
            return threads, existing
        if sum(thread.closure is None for thread in threads) >= MAX_OPEN:
            raise ValueError("Open causal thread limit reached; existing threads were preserved.")
        if any(
            thread.closure is None
            and thread.facts["purpose"].text.casefold() == facts["purpose"].text.casefold()
            for thread in threads
        ):
            raise ValueError("Update the existing purpose instead of opening a duplicate thread.")
        changed = Thread(id=identifier, actor_id=update.actor_id, origin=origin, facts=facts)
        result = [*threads, changed]
    else:
        if target is None:
            raise ValueError("Unknown causal thread.")
        changed = target.model_copy(
            update={
                "facts": {**target.facts, **facts},
                "closure": next(iter(facts.values())).source if update.action == "close" else None,
            }
        )
        result = [changed if thread.id == target.id else thread for thread in threads]
        if update.action == "close":
            result = [thread for thread in result if thread.id != changed.id] + [changed]
    closed = [thread for thread in result if thread.closure is not None]
    keep = {thread.id for thread in closed[-MAX_CLOSED:]}
    return [thread for thread in result if thread.closure is None or thread.id in keep], changed


def _anchor(reply: Any, quote: str) -> Anchor:
    if not quote or len(quote) > 600 or quote not in reply.content:
        raise ValueError("Causal update lacks an exact narration passage.")
    return Anchor(
        session_id=reply.session_id,
        message_id=reply.id,
        revision_id=reply.revision_id,
        content_hash=digest(reply.content),
        quote=quote,
    )


def retained(threads: list[Thread], invalid: set[str]) -> list[Thread]:
    return [
        thread
        for thread in threads
        if all(ref.message_id not in invalid for ref in anchors(thread))
    ]


def invalidate(turn: Any, actor: str, invalid: set[str]) -> None:
    turn.causal_threads[actor] = retained(turn.causal_threads.get(actor, []), invalid)
    if actor in turn.fallback_identities:
        turn.fallback_identities[actor]["causal_continuity_not_world_facts"] = view(
            turn.causal_threads[actor]
        )


def rebuild(memory: Memory, minds: dict[str, Mind]) -> Memory:
    actors = dict(memory.actors)
    for actor, mind in minds.items():
        if any(source.kind == "causal_state" for source in mind.sources.values()):
            actors[actor] = causal_graph.frontier(mind)
    return Memory(actors=actors)


def retract(memory: Memory, message_id: str, *, actor_id: str | None = None) -> Memory:
    return Memory(
        actors={
            actor: retained(threads, {message_id}) if actor_id in {None, actor} else threads
            for actor, threads in memory.actors.items()
        }
    )


def fork(memory: Memory, message_ids: dict[str, str], session_id: str) -> Memory:
    actors = {}
    for actor, threads in memory.actors.items():
        kept = [
            thread
            for thread in threads
            if all(ref.message_id in message_ids for ref in anchors(thread))
        ]
        actors[actor] = [_fork_thread(thread, message_ids, session_id) for thread in kept]
    return Memory(actors=actors)


def _fork_thread(thread: Thread, message_ids: dict[str, str], session_id: str) -> Thread:
    def rebind(ref: Anchor) -> Anchor:
        return ref.model_copy(
            update={"session_id": session_id, "message_id": message_ids[ref.message_id]}
        )

    return thread.model_copy(
        update={
            "origin": rebind(thread.origin),
            "facts": {
                key: fact.model_copy(update={"source": rebind(fact.source)})
                for key, fact in thread.facts.items()
            },
            "closure": rebind(thread.closure) if thread.closure else None,
        }
    )
