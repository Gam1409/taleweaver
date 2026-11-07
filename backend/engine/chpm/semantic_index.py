"""Idle embedding batches for saved observer ledgers, isolated from public memory."""

from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from backend.core import database
from backend.engine.chpm import control_settings, host_sources, semantic_sources
from backend.engine.chpm.state import KEY, load
from backend.engine.memory_rag.embeddings import embed_texts
from backend.engine.memory_rag.persistence import claim_fence, retry_transaction
from backend.engine.memory_rag.scheduling import BackgroundDeferredError, scheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState


async def index_batch(claim: Any, user: Any) -> bool:
    async with database.AsyncSessionLocal() as db:
        state = await db.scalar(
            select(SessionState)
            .join(GameSession, GameSession.id == SessionState.session_id)
            .where(
                SessionState.session_id == claim.session_id, GameSession.user_id == claim.user_id
            )
        )
        if state is None:
            return False
        settings = control_settings.read((state.entity_states or {}).get(KEY))
        if not settings.semantic_memory or settings.mode != "live":
            return False
        current = load(state)
        minds = {}
        host = SimpleNamespace(db=db, game_id=claim.session_id)
        for actor in settings.actor_ids:
            mind = current.minds.get(actor)
            if mind and mind.genesis.scope.world_id == claim.session_id:
                minds[actor] = await host_sources.reconcile(host, mind)
        ids = {s.message_id for mind in minds.values() for s in mind.sources.values()}
        rows = await semantic_sources.messages(db, claim.session_id, ids)
        items = [
            (episode, mind)
            for mind in minds.values()
            for episode in semantic_sources.episodes(mind, claim.user_id, state.template_id, rows)
        ]
    scope = (
        Scope(
            claim.user_id,
            claim.session_id,
            claim.epoch,
            semantic_sources.signature(claim.signature),
            namespace="observer",
        )
        if claim.signature
        else None
    )
    store = LanceMemoryStore()
    existing = await store.list_document_hashes(scope) if scope else {}
    valid_ids = {episode.document.id for episode, _ in items}
    pending = [
        (episode, mind)
        for episode, mind in items
        if existing.get(episode.document.id) != episode.document.source_hash
    ][:16]
    if not pending:
        if scope:
            await _write(claim, scope, [], [], valid_ids)
        return False
    if not scheduler.can_start_background():
        raise BackgroundDeferredError()
    vectors = await embed_texts(
        user, [semantic_sources.embedding_text(episode, mind) for episode, mind in pending]
    )
    base = embedding_signature(read_settings(user), len(vectors[0]))
    if claim.signature and base != claim.signature:
        raise ValueError("Embedding dimensions changed. Rebuild the memory index.")
    scope = Scope(
        claim.user_id,
        claim.session_id,
        claim.epoch,
        semantic_sources.signature(base),
        namespace="observer",
    )
    return await _write(
        claim, scope, [episode.document.to_dict() for episode, _ in pending], vectors, valid_ids
    )


@retry_transaction
async def _write(
    claim: Any, scope: Scope, documents: list[dict], vectors: list[list[float]], valid_ids: set[str]
) -> bool:
    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            update(MemoryIndexState)
            .where(*claim_fence(claim), MemoryIndexState.paused.is_(False))
            .values(updated_at=MemoryIndexState.updated_at)
        )
        if not cast(CursorResult[Any], result).rowcount:
            return False
        store = LanceMemoryStore()
        await store.upsert(scope, documents, vectors)
        await store.prune(scope, valid_ids)
        await store.prune_generations(scope)
        await db.commit()
        return True
