"""Actor-only World Info retrieval outside leases; SQL owns every returned fact."""

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from backend.core import database
from backend.core.llm_logger import log_structured_event
from backend.engine.living_world import event_recall, rules
from backend.engine.living_world.conflicts import SimulationConflict
from backend.engine.living_world.decision_context import context_for, fingerprint
from backend.engine.living_world.state import load
from backend.engine.memory_rag.documents import MemoryDocument, content_hash
from backend.engine.memory_rag.embeddings import embed_texts
from backend.engine.memory_rag.prompts import project
from backend.engine.memory_rag.ranking import rank_documents
from backend.engine.memory_rag.retrieval import VECTOR_SEARCH_GRACE, _canonical_scores
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.engine.world_info import projection
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class References:
    block: str = ""
    sources: tuple[tuple[str, str], ...] = ()
    owner: str = ""
    session: str = ""
    actor: str = ""
    timeline: str = ""
    configuration: str = ""
    generation: tuple | None = None


async def until_stopped(
    user: Any, session: str, actor: str, context: dict, fence: str, stop: asyncio.Event
) -> References:
    task = asyncio.create_task(retrieve(user, session, actor, context, fence))
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            raise HTTPException(409, "The private decision was stopped. No result was applied.")
        return task.result()
    finally:
        task.cancel()
        stopped.cancel()
        task.add_done_callback(_consume_late_result)
        await asyncio.gather(stopped, return_exceptions=True)


def _consume_late_result(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


def configuration(user: Any) -> str:
    return content_hash(read_settings(user).model_dump(mode="json"))


async def _index(db: Any, owner: str, session: str) -> Any:
    return await db.scalar(
        select(MemoryIndexState)
        .where(MemoryIndexState.user_id == owner, MemoryIndexState.session_id == session)
        .execution_options(populate_existing=True)
    )


def _generation(index: Any) -> tuple | None:
    return (index.epoch, index.signature, index.paused, index.template_id) if index else None


async def _state(db: Any, owner: str, session: str, actor: str) -> SessionState:
    state: SessionState | None = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == session, GameSession.user_id == owner)
        .execution_options(populate_existing=True)
    )
    npc = await rules.npc(db, state, actor) if state is not None else None
    if state is None or rules.unavailable_reason(state, npc):
        raise SimulationConflict("The reference actor or session changed. Retry the decision.")
    return state


async def _vectors(user: Any, scope: Scope | None, query: str, source_ids: list[str]) -> list[dict]:
    if scope is None or not source_ids:
        return []
    settings = read_settings(user)

    async def search() -> list[dict]:
        vectors = await embed_texts(
            user, [query], timeout=settings.timeout_seconds, purpose="query"
        )
        if embedding_signature(settings, len(vectors[0])) != scope.signature:
            return []
        return await LanceMemoryStore().query(
            scope, vectors[0], query, layers=[projection.LAYER], source_ids=source_ids, limit=32
        )

    try:
        return await asyncio.wait_for(search(), settings.timeout_seconds + VECTOR_SEARCH_GRACE)
    except Exception as exc:
        logger.debug("Actor reference vectors unavailable (%s); using SQL", type(exc).__name__)
        return []


def _scope(user: Any, state: Any, index: Any) -> Scope | None:
    if (
        index is None
        or index.paused
        or not index.signature
        or index.template_id != state.template_id
        or (not index.indexed_revision and index.status not in {"indexing", "pending"})
    ):
        return None
    return Scope(str(user.id), state.session_id, index.epoch, index.signature)


async def retrieve(user: Any, session: str, actor: str, context: dict, fence: str) -> References:
    """One optional embedding request; no transaction or session lease crosses it."""
    if not read_settings(user).enabled:
        return References()
    owner = str(user.id)
    started = time.perf_counter()
    query = event_recall.query(context) or str(context["actor"]["name"])
    async with database.AsyncSessionLocal() as db:
        state = await _state(db, owner, session, actor)
        await _check_fence(db, state, context, fence)
        index = await _index(db, owner, session)
        scope = _scope(user, state, index)
        source_ids = await projection.actor_source_ids(db, state, owner, actor) if scope else []
        await db.rollback()
        candidates = await _vectors(user, scope, query, source_ids)
        state = await _state(db, owner, session, actor)
        await _check_fence(db, state, context, fence)
        current_user = await db.get(User, owner, populate_existing=True)
        if current_user is None or configuration(current_user) != configuration(user):
            raise SimulationConflict("Reference recall settings changed. Retry the decision.")
        index = await _index(db, owner, session)
        if scope and _generation(index) != (scope.epoch, scope.signature, False, state.template_id):
            candidates = []
        documents = await projection.collect_documents(
            db, state, owner, query=query, candidates=candidates, actor_id=actor
        )
        scores = _canonical_scores(documents, candidates, scope) if scope and candidates else {}
        ranked = rank_documents(documents, query, {actor}, context["scene"]["id"], scores)
        expanded = await _expand(db, state, owner, actor, ranked)
        block, selected = project(
            expanded, audience="actor", actor_id=actor, actual_npc_ids={actor}, query=query
        )
        log_structured_event(
            "living_world.reference_recall",
            game_id=session,
            actor_id=actor,
            retrieval_method="hybrid" if scores else "sql_lexical",
            candidates=len(documents),
            expanded=len(expanded),
            selected=len(selected),
            source_ids=[doc.source_id for doc in selected],
            chars=len(block),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return References(
            block=block,
            sources=tuple((doc.source_id, doc.source_hash) for doc in selected),
            owner=owner,
            session=session,
            actor=actor,
            timeline=load(state).timeline,
            configuration=configuration(user),
            generation=_generation(index),
        )


async def _check_fence(db: Any, state: Any, context: dict, fence: str) -> None:
    simulation = load(state)
    event = next((item for item in simulation.events if item.event_id == context["event_id"]), None)
    if fingerprint(state, context) != fence or event is None:
        raise SimulationConflict(
            "The world changed during reference retrieval. Retry the decision."
        )
    current = await context_for(db, state, simulation, event)
    if fingerprint(state, current) != fence:
        raise SimulationConflict(
            "The actor context changed during reference retrieval. Retry the decision."
        )


async def _expand(
    db: Any, state: Any, owner: str, actor: str, ranked: list[MemoryDocument]
) -> list[MemoryDocument]:
    """One hop through authored links; both endpoints must pass current access."""
    targets = list(
        dict.fromkeys(target for doc in ranked[:4] for _, target in doc.reference_relations)
    )[:8]
    linked = (
        await projection.collect_documents(db, state, owner, actor_id=actor, source_ids=targets)
        if targets
        else []
    )
    by_source = {doc.source_id: doc for doc in [*ranked, *linked]}
    ordered: dict[str, MemoryDocument] = {}
    for doc in ranked:
        ordered.setdefault(doc.source_id, doc)
        ordered.update(
            {
                target: by_source[target]
                for _, target in doc.reference_relations
                if target in by_source and target not in ordered
            }
        )
    limit = projection.RECENT_ENTRIES + projection.LEXICAL_ENTRIES + projection.SEMANTIC_ENTRIES
    return [
        replace(
            doc,
            known_by=(actor,) if doc.audience == "restricted" else (),
            unresolved_known_by=(),
            reference_relations=tuple(
                link for link in doc.reference_relations if link[1] in by_source
            ),
        )
        for doc in list(ordered.values())[:limit]
        if doc.layer == projection.LAYER
    ]


async def validate(db: Any, state: Any, references: References) -> None:
    """Revalidate the immutable selected snapshot without network or reranking."""
    if not references.sources:
        return
    await _state(db, references.owner, references.session, references.actor)
    user = await db.get(User, references.owner, populate_existing=True)
    index = await _index(db, references.owner, references.session)
    if (
        state.session_id != references.session
        or load(state).timeline != references.timeline
        or user is None
        or configuration(user) != references.configuration
        or _generation(index) != references.generation
    ):
        raise SimulationConflict("The reference scope changed. The late result was discarded.")
    documents = await projection.collect_documents(
        db,
        state,
        references.owner,
        actor_id=references.actor,
        source_ids=[source for source, _ in references.sources],
    )
    if {doc.source_id: doc.source_hash for doc in documents} != dict(references.sources):
        raise SimulationConflict("Reference sources changed. The late result was discarded.")
