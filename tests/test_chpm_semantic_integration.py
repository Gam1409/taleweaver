"""Real SQL/Lance observer recall; deterministic test embeddings never call a model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio
from sqlalchemy import select

from backend.engine.chpm import semantic_index, semantic_recall
from backend.engine.chpm.host_state import Source, record, record_many
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState, Perception, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.memory_rag.scheduling import IdleScheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.engine.memory_rag.worker import Claim
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
ACTORS = ["SEM_RIN", "SEM_MIKI"]


@pytest_asyncio.fixture
async def semantic_world(portrait_world, tmp_path, monkeypatch):
    store = LanceMemoryStore(tmp_path)
    monkeypatch.setattr(semantic_index, "LanceMemoryStore", lambda: store)
    monkeypatch.setattr(semantic_recall, "LanceMemoryStore", lambda: store)
    monkeypatch.setattr(semantic_index, "scheduler", IdleScheduler(grace_seconds=0))
    calls = []

    async def embed(_user, texts, **kwargs):
        calls.append((list(texts), kwargs))
        return [
            [1.0, 0.0]
            if any(word in text.casefold() for word in ["sample", "specimen", "образец"])
            else [0.0, 1.0]
            for text in texts
        ]

    monkeypatch.setattr(semantic_index, "embed_texts", embed)
    monkeypatch.setattr(semantic_recall, "embed_texts", embed)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner = session.user_id
        user = await db.get(User, owner)
        user.llm_settings = {
            "memory_rag": {
                "enabled": True,
                "base_url": "http://localhost:11434",
                "model": "test-embed",
            }
        }
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session.id))
        values = {}
        for actor, text, place in zip(
            ACTORS,
            ["The sample is sealed in the blue vial.", "The access token is in my wallet."],
            ["CLINIC", "EMBASSY"],
            strict=True,
        ):
            message = ChatMessage(
                session_id=session.id, role="assistant", content=text, scene_id=place
            )
            db.add(message)
            await db.flush()
            item = Source(
                message_id=message.id,
                revision_id=message.revision_id,
                content_hash=digest(text),
                role="assistant",
                speaker_id=actor,
                kind="narration",
                text=text,
            )
            values[actor] = record(mind(actor, session.id), item, minute=1)
        kernel = KernelState(
            settings=Settings(mode="live", actor_ids=ACTORS, semantic_memory=True), minds=values
        )
        state.entity_states = {**(state.entity_states or {}), KEY: kernel.model_dump()}
        base = embedding_signature(read_settings(user), 2)
        index = MemoryIndexState(
            session_id=session.id,
            user_id=owner,
            template_id=state.template_id,
            epoch=3,
            signature=base,
            lease_token="test-token",
            desired_revision=1,
        )
        db.add(index)
        await db.commit()
    return owner, base, store, calls


async def _run_index(owner, base):
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        return await semantic_index.index_batch(
            Claim("portrait-session", owner, 3, 1, "test-token", base, False), user
        )


async def _turn(db, owner):
    user = await db.get(User, owner)
    state = await db.scalar(
        select(SessionState).where(SessionState.session_id == "portrait-session")
    )
    host = SimpleNamespace(db=db, user=user, state=state, game_id="portrait-session")
    turn = Turn(load(state), "input")
    turn.perceptions = {
        actor: Perception(actor_id=actor, quotes=["Where is the specimen?"]) for actor in ACTORS
    }
    return host, turn


async def test_idle_index_and_one_query_batch_find_paraphrases_with_observer_isolation(
    semantic_world,
):
    owner, base, store, calls = semantic_world
    assert await _run_index(owner, base)
    assert not await _run_index(owner, base)
    assert len(calls) == 1
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        await semantic_recall.prepare(
            host, turn, ACTORS, observation().model_copy(update={"session_id": host.game_id})
        )
        assert len(calls) == 2 and len(calls[-1][0]) == 2
        assert calls[-1][1]["purpose"] == "query"
        assert "sample" in turn.semantic_hits[ACTORS[0]][0].text
        assert all("sample" not in hit.text for hit in turn.semantic_hits[ACTORS[1]])
        assert turn.usage.calls == 0
        assert set(turn.usage.semantic_recall.values()) == {"hybrid"}
        assert turn.semantic_hits[ACTORS[0]][0].context.scene_id == "CLINIC"
        # Public search never sees rows from the private namespace.
        assert await store.query(Scope(owner, host.game_id, 3, base), [1.0, 0.0], "sample") == []


async def test_edit_after_vector_lookup_retracts_dependent_observer_sources(
    semantic_world, monkeypatch
):
    owner, base, store, _ = semantic_world
    assert await _run_index(owner, base)
    original = store.query
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        target = next(iter(turn.initial.minds[ACTORS[0]].sources.values())).message_id

        async def query(*args, **kwargs):
            result = await original(*args, **kwargs)
            row = await db.get(ChatMessage, target)
            row.content = "The previous report was corrected."
            row.revision_id = "new-revision"
            await db.commit()
            return result

        monkeypatch.setattr(store, "query", query)
        await semantic_recall.prepare(host, turn, [ACTORS[0]], observation())
        assert not turn.semantic_hits.get(ACTORS[0])
        assert not turn.reconciled_minds[ACTORS[0]].sources


async def test_epoch_change_during_lookup_cannot_publish_old_hits(semantic_world, monkeypatch):
    owner, base, store, _ = semantic_world
    assert await _run_index(owner, base)
    original = store.query
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)

        async def query(*args, **kwargs):
            result = await original(*args, **kwargs)
            index = await db.get(MemoryIndexState, host.game_id)
            index.epoch += 1
            await db.commit()
            return result

        monkeypatch.setattr(store, "query", query)
        await semantic_recall.prepare(host, turn, [ACTORS[0]], observation())
        assert not turn.semantic_hits


async def test_disabled_and_foreign_owner_indexing_submit_no_embeddings(
    semantic_world, monkeypatch
):
    owner, base, _, _ = semantic_world
    embed = AsyncMock(side_effect=AssertionError("No embeddings expected"))
    monkeypatch.setattr(semantic_index, "embed_texts", embed)
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        turn.initial.settings.semantic_memory = False
        host.state.entity_states = {KEY: turn.initial.model_dump()}
        await db.commit()
    assert not await _run_index(owner, base)
    claim = Claim("portrait-session", "foreign", 3, 1, "test-token", base, False)
    assert not await semantic_index.index_batch(claim, SimpleNamespace())
    embed.assert_not_awaited()


async def test_long_archived_history_keeps_old_semantic_evidence(semantic_world):
    owner, base, _, calls = semantic_world
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        original = turn.initial.minds[ACTORS[0]]
        additions = []
        for i in range(300):
            row = ChatMessage(
                session_id=host.game_id,
                role="assistant",
                content=f"Routine observation {i}.",
                scene_id="EMBASSY",
            )
            db.add(row)
            await db.flush()
            additions.append(
                Source(
                    message_id=row.id,
                    revision_id=row.revision_id,
                    content_hash=digest(row.content),
                    role="assistant",
                    speaker_id=ACTORS[0],
                    kind="narration",
                    text=row.content,
                )
            )
        turn.initial.minds[ACTORS[0]] = record_many(original, additions, minute=2)
        assert turn.initial.minds[ACTORS[0]].snapshot.archive
        host.state.entity_states = {KEY: turn.initial.model_dump()}
        await db.commit()
    for _ in range(30):
        if not await _run_index(owner, base):
            break
    else:
        raise AssertionError("Indexing did not finish within its bounded batch count")
    before = len(calls)
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        await semantic_recall.prepare(host, turn, [ACTORS[0]], observation())
        assert len(calls) == before + 1
        assert "blue vial" in turn.semantic_hits[ACTORS[0]][0].text
        assert turn.semantic_hits[ACTORS[0]][0].context.scene_id == "CLINIC"


async def test_twenty_observers_only_query_the_three_active_ones(semantic_world):
    owner, base, _, calls = semantic_world
    names = [f"OBSERVER_{i}" for i in range(20)]
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        shared = next(iter(turn.initial.minds[ACTORS[0]].sources.values()))
        turn.initial.minds = {
            actor: record(mind(actor, host.game_id), shared, minute=1) for actor in names
        }
        turn.initial.settings.actor_ids = names
        host.state.entity_states = {KEY: turn.initial.model_dump()}
        await db.commit()
    assert await _run_index(owner, base)
    assert await _run_index(owner, base)
    assert not await _run_index(owner, base)
    before = len(calls)
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        turn.perceptions = {
            actor: Perception(actor_id=actor, quotes=["Where is the specimen?"]) for actor in names
        }
        await semantic_recall.prepare(host, turn, names[:3], observation())
        assert len(calls) == before + 1 and len(calls[-1][0]) == 3
        assert set(turn.semantic_hits) == set(names[:3])
        assert len(turn.initial.minds) == 20


async def test_timeout_leaves_the_callers_session_and_state_usable(semantic_world, monkeypatch):
    import asyncio

    owner, base, _, _ = semantic_world
    assert await _run_index(owner, base)

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(semantic_recall, "embed_texts", slow)
    monkeypatch.setattr(semantic_recall, "FOREGROUND_EMBED_SECONDS", 0.02)
    monkeypatch.setattr(semantic_recall, "VECTOR_SEARCH_GRACE", 0.02)
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        await semantic_recall.prepare(host, turn, [ACTORS[0]], observation())
        assert not turn.semantic_hits
        assert host.state.session_id == "portrait-session"
        assert host.user.id == owner
        assert (
            await db.scalar(select(GameSession.id).where(GameSession.id == host.game_id))
            == host.game_id
        )


async def test_obsolete_private_rows_are_pruned_without_touching_public_memory(semantic_world):
    from backend.engine.chpm import semantic_sources

    owner, base, store, _ = semantic_world
    assert await _run_index(owner, base)
    private = Scope(
        owner, "portrait-session", 3, semantic_sources.signature(base), namespace="observer"
    )
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        turn.initial.minds[ACTORS[0]] = mind(ACTORS[0], host.game_id)
        host.state.entity_states = {KEY: turn.initial.model_dump()}
        await db.commit()
    assert not await _run_index(owner, base)
    assert not await store.query(private, [1.0, 0.0], "sample", npc_ids=[ACTORS[0]])
    assert await store.query(private, [0.0, 1.0], "token", npc_ids=[ACTORS[1]])


async def test_epoch_change_for_second_observer_discards_the_whole_batch(
    semantic_world, monkeypatch
):
    owner, base, store, _ = semantic_world
    assert await _run_index(owner, base)
    original = store.query
    calls = 0

    async def change_during_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        results = await original(*args, **kwargs)
        if calls == 2:
            async with TestSessionLocal() as writer:
                control = await writer.get(MemoryIndexState, "portrait-session")
                control.epoch += 1
                await writer.commit()
        return results

    monkeypatch.setattr(store, "query", change_during_second)
    async with TestSessionLocal() as db:
        host, turn = await _turn(db, owner)
        await semantic_recall.prepare(host, turn, ACTORS, observation())
        assert calls == 2
        assert not turn.semantic_hits
        assert set(turn.usage.semantic_recall.values()) == {"lexical_fallback"}
