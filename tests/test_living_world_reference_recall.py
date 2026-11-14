"""Real SQL actor references, optional embeddings and late-result validation."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import concordia_adapter, reference_recall
from backend.engine.living_world.decisions import Decision
from backend.engine.living_world.state import fork, load
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import Scope
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, searchable_text
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_living_world_decisions import configure, fake, post, ready, world
from tests.world_info_projection_fixture import seed_entry

__all__ = ["ready", "world"]


async def knowledge(*, index=False, enabled=True):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.llm_settings = {
            **user.llm_settings,
            "memory_rag": {
                "enabled": enabled,
                "base_url": "http://localhost:11434",
                "model": "test",
            },
        }
        actor = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LILI"
            )
        )
        actor.goal = "Recover the silver treaty."
        _, _, entry = await seed_entry(
            db,
            user.id,
            sid="session-1",
            audience="restricted",
            known_by=["LILI"],
            text="The silver treaty is kept in the archive.",
        )
        if index:
            db.add(
                MemoryIndexState(
                    user_id=user.id,
                    session_id="session-1",
                    template_id="template-1",
                    epoch=2,
                    signature=embedding_signature(read_settings(user), 2),
                    indexed_revision=1,
                )
            )
        await db.commit()
        return user.id, entry.id


@pytest.mark.parametrize("engine", ["native", "concordia"])
async def test_both_engines_share_scoped_reference_input_and_one_decision_call(
    ready, monkeypatch, engine
):
    owner, _ = await knowledge()
    async with TestSessionLocal() as db:
        await seed_entry(db, owner, sid="session-1", text="Private narrator silver treaty.")
        await seed_entry(
            db,
            owner,
            sid="session-1",
            audience="restricted",
            known_by=["MIRINDA"],
            text="Other actor silver treaty.",
        )
        await db.commit()
    adapter_inputs = []

    async def adapter(context, callback):
        adapter_inputs.append(context)
        return await callback()

    monkeypatch.setattr(concordia_adapter, "available", lambda: True)
    monkeypatch.setattr(concordia_adapter, "decide", adapter)
    embed = AsyncMock(side_effect=AssertionError("An unindexed session needs no embedding call"))
    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    await configure(ready, deliberation_enabled=True, mode="CATCH_UP", decision_engine=engine)
    captured = fake(monkeypatch)
    response = await post(ready)
    assert response.status_code == 200, response.text
    assert len(captured) == response.json()["llm_calls"] == 1
    block = captured[0]["reference_recall"]
    assert "silver treaty is kept" in block and "authored_reference" in block
    assert "Private narrator" not in block and "Other actor" not in block
    assert len(block) <= 2500
    assert adapter_inputs == ([captured[0]] if engine == "concordia" else [])
    embed.assert_not_awaited()


@pytest.mark.parametrize(
    "change", ["edit", "audience", "delete", "epoch", "rewind", "actor", "profile"]
)
async def test_retrieval_rechecks_sql_after_embedding_without_holding_lease_or_transaction(
    ready, monkeypatch, change
):
    owner, entry_id = await knowledge(index=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        index = await db.scalar(
            select(MemoryIndexState).where(MemoryIndexState.session_id == "session-1")
        )
        index.template_id = state.template_id
        old = (await projection.collect_documents(db, state, owner, actor_id="LILI"))[0]
        old_vector = old.to_dict() | {"epoch": 2, "signature": index.signature}
        await db.commit()
    readers = []

    def reader():
        db = TestSessionLocal()
        readers.append(db)
        return db

    async def embed(*args, **kwargs):
        assert readers and all(not db.in_transaction() for db in readers)
        with session_write_lease("session-1"):
            async with TestSessionLocal() as writer:
                await change_source(writer, change, entry_id)
                await writer.commit()
        return [[1.0, 0.0]]

    monkeypatch.setattr(reference_recall.database, "AsyncSessionLocal", reader)
    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    query = AsyncMock(return_value=[old_vector])
    monkeypatch.setattr(reference_recall.LanceMemoryStore, "query", query)
    captured = fake(monkeypatch)
    response = await post(ready)
    if change in {"rewind", "actor", "profile"}:
        assert response.status_code == 409, response.text
        assert captured == []
        return
    assert response.status_code == 200, response.text
    block = captured[0].get("reference_recall", "")
    assert ("silver treaty is kept" in block) == (change == "epoch")
    assert ("silver treaty has moved" in block) == (change == "edit")
    assert query.call_args.kwargs["layers"] == ["world_info"]
    assert query.call_args.kwargs["source_ids"] == [old.source_id]


async def change_source(db, change, entry_id):
    if change == "delete":
        await db.execute(delete(WorldInfoEntry).where(WorldInfoEntry.id == entry_id))
        return
    if change == "actor":
        await db.execute(
            delete(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LILI"
            )
        )
        return
    if change == "profile":
        actor = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LILI"
            )
        )
        actor.goal = "A different current objective."
        return
    if change == "rewind":
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        state.living_world = fork(state.living_world)
        return
    if change == "epoch":
        index = await db.scalar(
            select(MemoryIndexState).where(MemoryIndexState.session_id == "session-1")
        )
        index.epoch += 1
        return
    entry = await db.get(WorldInfoEntry, entry_id)
    entry.version += 1
    if change == "audience":
        entry.audience, entry.known_by = "narrator_only", []
        return
    facts = deepcopy(entry.facts)
    facts[0].update(text="The silver treaty has moved to a different archive.", edited=True)
    entry.facts = facts
    entry.search_text = searchable_text(
        EntryDraft.model_validate({key: getattr(entry, key) for key in EntryDraft.model_fields})
    )


@pytest.mark.parametrize("change", ["edit", "audience", "delete", "epoch"])
async def test_selected_source_change_during_inference_discards_late_decision(
    ready, monkeypatch, change
):
    _, entry_id = await knowledge(index=change == "epoch")
    if change == "epoch":
        monkeypatch.setattr(reference_recall, "_vectors", AsyncMock(return_value=[]))

    async def generate(self, instruction, supplied, model, **kwargs):
        assert "silver treaty is kept" in json.loads(supplied)["reference_recall"]
        async with TestSessionLocal() as writer:
            await change_source(writer, change, entry_id)
            await writer.commit()
        return Decision(
            action="WAIT", goal="Continue searching.", belief="Maybe."
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    response = await post(ready)
    assert response.status_code == 409, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert not load(state).private_notes


@pytest.mark.parametrize("mode", ["disabled", "failure", "paused"])
async def test_optional_retrieval_keeps_disabled_and_embedding_failure_semantics(
    ready, monkeypatch, mode
):
    await knowledge(index=mode != "disabled", enabled=mode != "disabled")
    embed = AsyncMock(side_effect=RuntimeError("Unavailable optional embeddings"))
    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    async with TestSessionLocal() as db:
        index = await db.scalar(
            select(MemoryIndexState).where(MemoryIndexState.session_id == "session-1")
        )
        if index:
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == "session-1")
            )
            index.template_id, index.paused = state.template_id, mode == "paused"
            await db.commit()
    captured = fake(monkeypatch)
    response = await post(ready)
    assert response.status_code == 200, response.text
    assert ("reference_recall" in captured[0]) == (mode != "disabled")
    assert embed.await_count == (1 if mode == "failure" else 0)


async def test_stop_cancels_pending_retrieval_without_a_decision_call(ready, monkeypatch):
    await knowledge(index=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        index = await db.scalar(
            select(MemoryIndexState).where(MemoryIndexState.session_id == "session-1")
        )
        index.template_id = state.template_id
        await db.commit()
    entered = asyncio.Event()

    async def embed(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    captured = fake(monkeypatch)
    task = asyncio.create_task(post(ready))
    await asyncio.wait_for(entered.wait(), 5)
    assert (await ready.post("/api/adventures/session-1/living-world/stop")).status_code == 200
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409 and captured == []


async def test_one_hop_preserves_conflicts_and_uncertainty_without_exposing_hidden_targets(
    ready, monkeypatch
):
    owner, entry_id = await knowledge()
    async with TestSessionLocal() as db:
        _, _, contrary = await seed_entry(
            db,
            owner,
            sid="session-1",
            audience="common_knowledge",
            text="All collections are closed indefinitely.",
        )
        _, _, secret = await seed_entry(
            db, owner, sid="session-1", text="A private hidden assertion."
        )
        contrary.kind = "news"
        main = await db.get(WorldInfoEntry, entry_id)
        main.kind, main.known_by = "rumor", ["LILI", "MIRINDA"]
        main.relations = [
            {"target_id": contrary.id, "kind": "contradicts", "note": ""},
            {"target_id": secret.id, "kind": "supports", "note": ""},
        ]
        await db.commit()
        contrary_id, secret_id = contrary.id, secret.id
    captured = fake(monkeypatch)
    response = await post(ready)
    assert response.status_code == 200, response.text
    block = captured[0]["reference_recall"]
    assert "silver treaty is kept" in block and "All collections are closed" in block
    assert "unverified rumor" in block and "attributed report" in block
    assert contrary_id in block and "contradicts" in block
    assert secret_id not in block and "private hidden" not in block and "MIRINDA" not in block
    assert len(block) <= 2500


async def test_vector_outage_has_a_hard_deadline_and_keeps_sql_fallback(monkeypatch):
    user = SimpleNamespace(llm_settings={"memory_rag": {"enabled": True}})
    settings = read_settings(user).model_copy(update={"timeout_seconds": 0.01})

    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(reference_recall, "read_settings", lambda _: settings)
    monkeypatch.setattr(reference_recall, "VECTOR_SEARCH_GRACE", 0.01)
    monkeypatch.setattr(reference_recall, "embed_texts", blocked)
    assert (
        await asyncio.wait_for(
            reference_recall._vectors(
                user, Scope("owner", "session", 1, "signature"), "query", ["world_info:one"]
            ),
            0.5,
        )
        == []
    )


async def test_real_concordia_adapter_receives_the_same_actor_reference_contract(
    ready, monkeypatch
):
    if not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    await knowledge()
    await configure(ready, deliberation_enabled=True, mode="CATCH_UP", decision_engine="concordia")
    captured = fake(monkeypatch)
    response = await post(ready)
    assert response.status_code == 200, response.text
    assert len(captured) == response.json()["llm_calls"] == 1
    assert "silver treaty is kept" in captured[0]["reference_recall"]
