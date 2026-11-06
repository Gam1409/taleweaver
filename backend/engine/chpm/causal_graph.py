"""Immutable statement and influence records in the observer's existing evidence journal."""

from typing import Any

from backend.engine.chpm.causal_contracts import MAX_CLOSED, MAX_OPEN, Anchor, Fact, Thread, Update
from backend.engine.chpm.causal_graph_contracts import Binding, FactKey, LinkDraft
from backend.engine.chpm.host_state import Mind, Source, identifier, record_many
from backend.engine.chpm.kernel import digest


def _records(mind: Mind) -> list[tuple[str, Source]]:
    # JSON object key order is not chronology. The validated evidence projection
    # retains observation sequence across serialization, archive and session copies.
    return [(entry.event_id, mind.sources[entry.event_id]) for entry in mind.snapshot.evidence]


def narration(actor: str, fact: Fact) -> Source:
    ref = fact.source
    return Source(
        message_id=ref.message_id,
        revision_id=ref.revision_id,
        content_hash=ref.content_hash,
        role="assistant",
        speaker_id=actor,
        kind="narration",
        text=ref.quote,
    )


def statement(mind: Mind, thread: Thread, key: FactKey) -> Source:
    fact = thread.facts[key]
    original = narration(thread.actor_id, fact)
    return Source(
        message_id=original.message_id,
        revision_id=original.revision_id,
        content_hash=original.content_hash,
        role="assistant",
        speaker_id=thread.actor_id,
        kind="causal_fact",
        text=fact.text,
        graph=Binding(
            thread_id=thread.id,
            field=key,
            parents=(identifier(original, mind.genesis),),
            quote=original.text,
        ),
    )


def remember(
    mind: Mind, thread: Thread, update: Update, reply: Any, available: dict[str, str]
) -> tuple[Mind, list[str]]:
    if thread.actor_id != mind.genesis.scope.observer_id:
        raise ValueError("Causal graph belongs to another NPC.")
    originals = [narration(thread.actor_id, fact) for fact in thread.facts.values()]
    statements = {key: statement(mind, thread, key) for key in thread.facts}
    nodes = {key: identifier(source, mind.genesis) for key, source in statements.items()}
    edges, notes = [], []
    for raw in update.links:
        try:
            link = LinkDraft.model_validate(raw)
            edges.append(_edge(link, thread, nodes, reply, available))
        except ValueError as exc:
            notes.append("Skipped influence link: " + str(exc).splitlines()[0][:180])
    transition = _transition(mind, thread, update, nodes, reply, available)
    changed = record_many(
        mind,
        [*originals, *statements.values(), *edges, transition],
        minute=mind.snapshot.sim_minute,
    )
    return changed, notes


def _transition(
    mind: Mind,
    thread: Thread,
    update: Update,
    nodes: dict[FactKey, str],
    reply: Any,
    available: dict[str, str],
) -> Source:
    prior = next(
        (
            (key, source)
            for key, source in reversed(_records(mind))
            if source.kind == "causal_state"
            and source.graph
            and source.graph.thread_id == thread.id
        ),
        None,
    )
    quote = available[next(iter(update.facts.values())).passage_id]
    parents = tuple(nodes.values())
    prior_binding = prior[1].graph if prior else None
    if (
        prior
        and prior_binding
        and prior[1].message_id == reply.id
        and prior_binding.action == update.action
        and prior_binding.parents == parents
    ):
        return prior[1]
    return Source(
        message_id=reply.id,
        revision_id=reply.revision_id,
        content_hash=digest(reply.content),
        role="assistant",
        speaker_id=thread.actor_id,
        kind="causal_state",
        text=f"{update.action} causal thread",
        graph=Binding(
            thread_id=thread.id,
            action=update.action,
            parents=parents,
            quote=quote,
            previous=prior[0] if prior else None,
        ),
    )


def frontier(mind: Mind) -> list[Thread]:
    """Rebuild the small current view from retained events, including after rewind."""
    latest: dict[str, Thread] = {}
    for _, source in _records(mind):
        binding = source.graph
        if source.kind != "causal_state" or binding is None:
            continue
        facts: dict[FactKey, Fact] = {}
        for parent_id in binding.parents:
            parent = mind.sources[parent_id]
            if parent.graph is None or parent.graph.field is None:
                raise ValueError("Causal transition has an invalid statement parent.")
            facts[parent.graph.field] = Fact(text=parent.text, source=_anchor(mind, parent))
        previous = latest.pop(binding.thread_id, None)
        latest[binding.thread_id] = Thread(
            id=binding.thread_id,
            actor_id=mind.genesis.scope.observer_id,
            origin=previous.origin if previous else _anchor(mind, source),
            facts=facts,
            closure=_anchor(mind, source) if binding.action == "close" else None,
        )
    active = [thread for thread in latest.values() if thread.closure is None]
    if len(active) > MAX_OPEN:
        raise ValueError("Causal graph has too many open threads; none were discarded.")
    return (
        active + [thread for thread in latest.values() if thread.closure is not None][-MAX_CLOSED:]
    )


def _anchor(mind: Mind, source: Source) -> Anchor:
    return Anchor(
        session_id=mind.genesis.scope.world_id,
        message_id=source.message_id,
        revision_id=source.revision_id,
        content_hash=source.content_hash,
        quote=source.evidence_quote,
    )


def _edge(
    link: LinkDraft,
    thread: Thread,
    nodes: dict[FactKey, str],
    reply: Any,
    available: dict[str, str],
) -> Source:
    if link.source not in nodes or link.target not in nodes:
        raise ValueError("Influence refers to a statement absent from its owned thread.")
    quote = available.get(link.passage_id, "")
    if not quote or len(quote) > 600 or quote not in reply.content:
        raise ValueError("Influence needs an exact current narration passage.")
    return Source(
        message_id=reply.id,
        revision_id=reply.revision_id,
        content_hash=digest(reply.content),
        role="assistant",
        speaker_id=thread.actor_id,
        kind="causal_link",
        text=f"{link.source} {link.relation} {link.target}",
        graph=Binding(
            thread_id=thread.id,
            parents=(nodes[link.source], nodes[link.target]),
            relation=link.relation,
            attribution=link.attribution,
            quote=quote,
        ),
    )


def current_links(mind: Mind, thread: Thread) -> list[dict]:
    fields = {identifier(statement(mind, thread, key), mind.genesis): key for key in thread.facts}
    result = []
    seen = set()
    for _, source in reversed(_records(mind)):
        binding = source.graph
        if source.kind != "causal_link" or binding is None or binding.thread_id != thread.id:
            continue
        if not all(parent in fields for parent in binding.parents):
            continue
        key = (binding.parents, binding.relation)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "source": fields[binding.parents[0]],
                "target": fields[binding.parents[1]],
                "relation": binding.relation,
                "attribution": binding.attribution,
            }
        )
        if len(result) == 3:
            break
    return result


def projection(mind: Mind) -> dict[str, list[dict]]:
    """Administrator trace; full history stays out of the per-turn model payload."""
    nodes, links, transitions = [], [], []
    for key, source in _records(mind):
        binding = source.graph
        if binding is None:
            continue
        item = {
            "id": key,
            "thread_id": binding.thread_id,
            "text": source.text,
            "source_message_id": source.message_id,
            "quote": binding.quote,
        }
        if binding.field is not None:
            nodes.append({**item, "field": binding.field})
        elif binding.relation is not None:
            links.append(
                {
                    **item,
                    "source": binding.parents[0],
                    "target": binding.parents[1],
                    "relation": binding.relation,
                    "attribution": binding.attribution,
                }
            )
        else:
            transitions.append(
                {
                    **item,
                    "action": binding.action,
                    "facts": list(binding.parents),
                    "previous": binding.previous,
                }
            )
    return {"nodes": nodes, "links": links, "transitions": transitions}
