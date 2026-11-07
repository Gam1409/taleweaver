"""One bounded embedding batch per turn, over each NPC's retained evidence only."""

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from backend.core import database
from backend.engine.chpm import host_sources, semantic_sources
from backend.engine.chpm.agent_limits import MAX_PINNED_CHARS, MAX_PINNED_SOURCES
from backend.engine.chpm.host_state import Mind, Source
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import EpisodeContext
from backend.engine.memory_rag.embeddings import embed_texts
from backend.engine.memory_rag.retrieval import FOREGROUND_EMBED_SECONDS, VECTOR_SEARCH_GRACE
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hit:
    record_id: str
    text: str
    context: EpisodeContext
    score: float


async def prepare(manager: Any, turn: Any, actor_ids: list[str], observation: Any) -> None:
    if not turn.initial.settings.semantic_memory or turn.initial.settings.mode != "live":
        return
    turn.usage.semantic_recall = {actor: "lexical_fallback" for actor in actor_ids}
    if not read_settings(manager.user).enabled:
        return
    try:
        await asyncio.wait_for(
            _read(manager, turn, actor_ids, observation),
            FOREGROUND_EMBED_SECONDS + VECTOR_SEARCH_GRACE,
        )
    except ChpmError:
        raise
    except Exception as exc:
        # Optional retrieval never retries transport, clears an uncertain lease,
        # or substitutes another observer's data when embeddings are unavailable.
        logger.debug(
            "Optional observer recall unavailable (%s); using lexical memory", type(exc).__name__
        )


async def _read(manager: Any, turn: Any, actors: list[str], observation: Any) -> None:
    # A timeout can invalidate its read connection without expiring the turn's
    # ORM objects or rolling back the caller's recoverable world changes.
    async with database.AsyncSessionLocal() as db:
        reader = SimpleNamespace(
            db=db, user=manager.user, state=manager.state, game_id=manager.game_id
        )
        await _prepare(reader, turn, actors, observation)


async def _prepare(manager: Any, turn: Any, actors: list[str], observation: Any) -> None:
    owner = await manager.db.scalar(
        select(GameSession.id).where(
            GameSession.id == manager.game_id, GameSession.user_id == manager.user.id
        )
    )
    if owner is None:
        raise ChpmError("Semantic memory belongs to another session owner.")
    index = await manager.db.scalar(
        select(MemoryIndexState)
        .where(
            MemoryIndexState.session_id == manager.game_id,
            MemoryIndexState.user_id == manager.user.id,
        )
        .execution_options(populate_existing=True)
    )
    if index is None or index.paused or not index.signature:
        return
    eligible = await _eligible(manager, turn, actors)
    if not eligible:
        return
    expected = index.epoch, index.signature
    await manager.db.commit()
    queries = [_query(turn, actor, observation.scene_id) for actor, _ in eligible]
    vectors = await embed_texts(
        manager.user, queries, timeout=FOREGROUND_EMBED_SECONDS, purpose="query"
    )
    base = embedding_signature(read_settings(manager.user), len(vectors[0]))
    if expected[1] != base:
        return
    scope = Scope(
        str(manager.user.id),
        str(manager.game_id),
        expected[0],
        semantic_sources.signature(base),
        namespace="observer",
    )
    hits_by_actor = {}
    for (actor, mind), vector, query in zip(eligible, vectors, queries, strict=True):
        hits = await _retrieve(manager, turn, actor, mind, vector, query, scope, base)
        if hits is None:
            return
        hits_by_actor[actor] = hits
    # Publish a consistent generation only after every observer passes the fence.
    turn.semantic_hits.update(hits_by_actor)
    turn.usage.semantic_recall.update(
        {actor: "hybrid" if hits else "no_matches" for actor, hits in hits_by_actor.items()}
    )


async def _eligible(manager: Any, turn: Any, actors: list[str]) -> list[tuple[str, Mind]]:
    eligible = []
    for actor in actors:
        mind = turn.reconciled_minds.get(actor) or turn.initial.minds.get(actor)
        if mind is None:
            turn.usage.semantic_recall[actor] = "not_indexed"
            continue
        if (
            mind.genesis.scope.world_id != manager.game_id
            or mind.genesis.scope.observer_id != actor
        ):
            raise ChpmError("Semantic memory belongs to another NPC or session.")
        if actor not in turn.reconciled_minds:
            mind = await host_sources.reconcile(manager, mind)
            turn.reconciled_minds[actor] = mind
        eligible.append((actor, mind))
    return eligible


async def _retrieve(
    manager: Any,
    turn: Any,
    actor: str,
    saved: Mind,
    vector: list[float],
    query: str,
    scope: Scope,
    base: str,
) -> list[Hit] | None:
    candidates = await LanceMemoryStore().query(scope, vector, query, npc_ids=[actor], limit=12)
    # Canonical text and metadata are read after the network/storage awaits.
    rows = await semantic_sources.messages(
        manager.db, manager.game_id, {s.message_id for s in saved.sources.values()}
    )
    checked = host_sources.from_messages(saved, rows)
    turn.reconciled_minds[actor] = checked
    current = await manager.db.scalar(
        select(MemoryIndexState)
        .where(
            MemoryIndexState.session_id == manager.game_id,
            MemoryIndexState.user_id == manager.user.id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        current is None
        or current.paused
        or (current.epoch, current.signature) != (scope.epoch, base)
    ):
        return None
    return validate(
        checked, str(manager.user.id), manager.state.template_id, rows, candidates, scope
    )


def _query(turn: Any, actor: str, scene: str) -> str:
    perceived = turn.perceptions[actor]
    reasons = [
        fact.text
        for thread in turn.causal_threads.get(actor, [])
        if thread.closure is None
        for fact in thread.facts.values()
    ]
    return (
        "\n".join(perceived.quotes)[:1600]
        + f"\nScene: {scene}.\nOngoing circumstances: "
        + " ".join(reasons)[:1000]
    )[:3000]


def validate(
    mind: Mind,
    owner: str,
    template_id: str | None,
    rows: dict,
    candidates: list[dict],
    scope: Scope,
) -> list[Hit]:
    if (
        scope.namespace != "observer"
        or scope.user_id != owner
        or scope.session_id != mind.genesis.scope.world_id
    ):
        raise ChpmError("Semantic retrieval scope differs from its observer.")
    canonical = {
        item.document.id: item for item in semantic_sources.episodes(mind, owner, template_id, rows)
    }
    result, seen = [], set()
    for rank, candidate in enumerate(candidates[:12]):
        item = canonical.get(str(candidate.get("id") or ""))
        if item is None or item.record_id in seen:
            continue
        expected = (
            owner,
            scope.session_id,
            scope.epoch,
            scope.signature,
            mind.genesis.scope.observer_id,
            item.document.source_hash,
            item.document.template_id or "",
            "observer",
            item.document.source_id,
        )
        actual = tuple(
            candidate.get(key)
            for key in (
                "user_id",
                "session_id",
                "epoch",
                "signature",
                "npc_id",
                "source_hash",
                "template_id",
                "layer",
                "source_id",
            )
        )
        if actual != expected:
            continue
        seen.add(item.record_id)
        result.append(
            Hit(
                item.record_id,
                item.document.text,
                EpisodeContext(scene_id=item.document.scene_id, evidence_order=item.evidence_order),
                1 / (1 + rank),
            )
        )
    return result


def merge(
    mind: Mind, existing: dict[str, tuple[str, Source, str]], hits: list[Hit]
) -> dict[str, tuple[str, Source, str]]:
    pins = dict(existing)
    known = {item[0] for item in pins.values()}
    for hit in hits[:2]:
        source = mind.sources.get(hit.record_id)
        if source is None or hit.record_id in known or hit.text not in source.text:
            continue
        if (
            len(pins) >= MAX_PINNED_SOURCES
            or sum(len(item[2]) for item in pins.values()) + len(hit.text) > MAX_PINNED_CHARS
        ):
            continue
        pins[f"v{len(pins) + 1}"] = (hit.record_id, source, hit.text)
        known.add(hit.record_id)
    return pins


def contexts(pins: dict, hits: list[Hit]) -> dict[str, EpisodeContext]:
    selected = {item[0] for item in pins.values()}
    return {hit.record_id: hit.context for hit in hits if hit.record_id in selected}
