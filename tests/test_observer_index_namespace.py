"""Public-index maintenance cannot expose or erase an observer's private memory."""

from dataclasses import replace

from backend.engine.memory_rag import store as store_module
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from tests.test_memory_rag_embeddings_store import _doc


async def test_public_and_observer_generations_are_independent_and_owner_clear_removes_both(
    tmp_path,
):
    store = LanceMemoryStore(tmp_path)
    public = Scope("owner", "session", 2, "public-model")
    observer = Scope("owner", "session", 2, "observer-model", namespace="observer")
    private_doc = {**_doc(), "layer": "observer", "npc_id": "RIN"}
    await store.upsert(public, [_doc()], [[1.0, 0.0]])
    await store.upsert(observer, [private_doc], [[1.0, 0.0]])
    await store.upsert(replace(observer, epoch=1), [private_doc], [[1.0, 0.0]])
    assert await store.prune_generations(public) == 0
    assert len(await store.query(observer, [1.0, 0.0], "", npc_ids=["RIN"])) == 1
    assert await store.prune_generations(observer) == 1
    assert len(await store.query(public, [1.0, 0.0], "")) == 1
    assert await store.query(observer, [1.0, 0.0], "", npc_ids=["MIKI"]) == []
    assert await store.delete_session("owner", "session") == 2


async def test_namespace_filters_remain_effective_even_if_signatures_are_equal(tmp_path):
    store = LanceMemoryStore(tmp_path)
    public = Scope("owner", "session", 0, "model")
    private = replace(public, namespace="observer")
    await store.upsert(public, [_doc()], [[1.0, 0.0]])
    await store.upsert(
        private, [{**_doc(), "id": "private", "layer": "observer", "npc_id": "RIN"}], [[1.0, 0.0]]
    )
    assert [row["id"] for row in await store.query(public, [1.0, 0.0], "")] == [_doc()["id"]]
    assert [row["id"] for row in await store.query(private, [1.0, 0.0], "")] == ["private"]


async def test_hash_catalog_paginates_without_a_hidden_source_count_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "HASH_PAGE_SIZE", 2)
    store = LanceMemoryStore(tmp_path)
    scope = Scope("owner", "session", 0, "model")
    items = [_doc(str(i)) for i in range(5)]
    await store.upsert(scope, items, [[1.0, 0.0]] * 5)
    assert set(await store.list_document_hashes(scope)) == {item["id"] for item in items}


async def test_same_document_id_cannot_overwrite_another_namespace(tmp_path):
    store = LanceMemoryStore(tmp_path)
    public = Scope("owner", "session", 0, "model")
    private = replace(public, namespace="observer")
    await store.upsert(public, [_doc()], [[1.0, 0.0]])
    await store.upsert(private, [{**_doc(), "layer": "observer"}], [[1.0, 0.0]])
    assert len(await store.query(public, [1.0, 0.0], "")) == 1
    assert len(await store.query(private, [1.0, 0.0], "")) == 1
