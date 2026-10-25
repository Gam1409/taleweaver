"""Offline HTTP transport fixtures and real temporary LanceDB isolation tests."""

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from backend.engine.memory_rag import embeddings
from backend.engine.memory_rag.embeddings import EmbeddingError, embed_texts, validate_vectors
from backend.engine.memory_rag.settings import MemoryRagSettings, embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope


def _user(provider="openai"):
    return SimpleNamespace(
        llm_settings={
            "memory_rag": {
                "enabled": True,
                "provider": provider,
                "base_url": "http://localhost:11434",
                "model": "test-embed",
            }
        },
        encrypted_api_keys={},
    )


def _mock_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)
    monkeypatch.setattr(
        embeddings.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,path,payload",
    [
        (
            "openai",
            "/v1/embeddings",
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        ),
        ("ollama", "/api/embed", {"embeddings": [[1.0, 0.0], [0.0, 1.0]]}),
    ],
)
async def test_embedding_only_requests_and_order(monkeypatch, provider, path, payload):
    def handler(request):
        assert request.url.path == path
        assert request.method == "POST"
        assert json.loads(request.content) == {"model": "test-embed", "input": ["first", "second"]}
        assert "authorization" not in request.headers
        return httpx.Response(200, json=payload)

    _mock_transport(monkeypatch, handler)
    assert await embed_texts(_user(provider), ["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.asyncio
async def test_secret_from_independent_encrypted_vault(monkeypatch):
    from backend.core.security import encryption_util

    user = _user()
    user.encrypted_api_keys = {"memory_embeddings": encryption_util.encrypt_key("test-key")}

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    _mock_transport(monkeypatch, handler)
    assert await embed_texts(user, ["first"]) == [[1.0]]


@pytest.mark.parametrize(
    "vectors,count",
    [
        ([[float("nan")]], 1),
        ([[float("inf")]], 1),
        ([[True]], 1),
        ([[]], 1),
        ([[1], [1, 2]], 2),
        ([[1]], 2),
        ([["1"]], 1),
    ],
)
def test_invalid_vector_responses(vectors, count):
    with pytest.raises(EmbeddingError):
        validate_vectors(vectors, count)


@pytest.mark.asyncio
async def test_failed_provider_payload_is_not_exposed(monkeypatch):
    _mock_transport(
        monkeypatch, lambda request: httpx.Response(500, text="secret-key private data")
    )
    with pytest.raises(EmbeddingError, match="check the endpoint") as error:
        await embed_texts(_user(), ["first"])
    assert "secret-key" not in str(error.value)


@pytest.mark.asyncio
async def test_embedding_timeout_is_bounded(monkeypatch):
    async def handler(request):
        raise httpx.ReadTimeout("secret provider url")

    _mock_transport(monkeypatch, handler)
    with pytest.raises(EmbeddingError):
        await embed_texts(_user(), ["first"], timeout=0.1)


def test_settings_are_opt_in_and_signature_has_dimensions():
    assert not read_settings(SimpleNamespace(llm_settings={})).enabled
    settings = MemoryRagSettings(base_url=" HTTP://LOCALHOST:8000/v1/ ", model=" embed ")
    same = MemoryRagSettings(base_url="http://localhost:8000/v1", model="embed")
    assert embedding_signature(settings, 2) == embedding_signature(same, 2)
    assert embedding_signature(settings, 2) != embedding_signature(settings, 3)
    assert embedding_signature(settings, 2) != embedding_signature(
        settings.model_copy(update={"model": "other"}), 2
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@localhost",
        "http://localhost/?key=secret",
        "file:///tmp/test",
        "http://localhost/#fragment",
    ],
)
def test_unsafe_url_shapes(url):
    with pytest.raises(ValueError):
        MemoryRagSettings(base_url=url)


def _doc(doc_id="one", **overrides):
    return dict(
        id=doc_id,
        template_id="template",
        layer="dialogue",
        source_id=doc_id,
        source_hash="hash-" + doc_id,
        text="Remember silver locket",
        npc_id="npc",
        scene_id="scene",
        provenance="player",
        source_message_ids=[doc_id],
        **overrides,
    )


@pytest.mark.asyncio
async def test_real_lancedb_isolation_replacement_pruning_and_clear(tmp_path):
    store = LanceMemoryStore(tmp_path / "memory")
    scope = Scope("user", "session", 1, "model-v1")
    outsiders = [
        replace(scope, user_id="other"),
        replace(scope, session_id="other"),
        replace(scope, epoch=2),
        replace(scope, signature="other"),
    ]
    await store.upsert(scope, [_doc()], [[1.0, 0.0]])
    for outsider in outsiders:
        await store.upsert(outsider, [_doc()], [[1.0, 0.0]])
    rows = await store.query(
        scope, [1.0, 0.0], "silver locket", layers=["dialogue"], npc_ids=["npc"], scene_id="scene"
    )
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user"
    assert rows[0]["source_message_ids"] == ["one"]
    assert "vector" not in rows[0]
    assert await store.query(scope, [1.0, 0.0], "locket", npc_ids=["other"]) == []
    assert await store.query(scope, [1.0, 0.0], "locket", layers=[]) == []
    changed = _doc()
    changed.update(text="New copper token", source_hash="new")
    await store.upsert(scope, [changed, _doc("two")], [[0.0, 1.0], [1.0, 0.0]])
    assert await store.list_document_hashes(scope) == {"one": "new", "two": "hash-two"}
    assert await store.prune(scope, ["one"]) == 1
    assert await store.delete_session("user", "session") == 3
    assert await store.query(scope, [1.0, 0.0], "locket") == []
    assert len(await store.query(outsiders[0], [1.0, 0.0], "locket")) == 1
    assert len(await store.query(outsiders[1], [1.0, 0.0], "locket")) == 1


@pytest.mark.asyncio
async def test_lancedb_escaping_and_dimension_rejection(tmp_path):
    store = LanceMemoryStore(tmp_path)
    scope = Scope("user' OR true --", "adventure'quoted", 0, "embedding/v1")
    await store.upsert(scope, [_doc()], [[1.0, 0.0]])
    await store.upsert(replace(scope, user_id="other"), [_doc()], [[1.0, 0.0]])
    assert len(await store.query(scope, [1.0, 0.0], "silver' OR true")) == 1
    with pytest.raises(ValueError, match="dimension"):
        await store.upsert(scope, [_doc()], [[1.0]])
    with pytest.raises(ValueError, match="ownership"):
        await store.upsert(scope, [_doc(user_id="other")], [[1.0, 0.0]])
    assert await store.delete_scope(scope) == 1
    assert len(await store.query(replace(scope, user_id="other"), [1.0, 0.0], "silver")) == 1


@pytest.mark.asyncio
async def test_template_clear_includes_old_sessions_and_signatures(tmp_path):
    store = LanceMemoryStore(tmp_path)
    scope = Scope("user", "deleted-session", 0, "old-model")
    await store.upsert(scope, [_doc()], [[1.0, 0.0]])
    await store.upsert(replace(scope, signature="new-model"), [_doc()], [[1.0]])
    await store.upsert(replace(scope, user_id="other"), [_doc()], [[1.0, 0.0]])
    assert await store.count_template("user", "template") == 2
    assert await store.delete_template("user", "template") == 2
    assert await store.count_template("user", "template") == 0
    assert await store.count_template("other", "template") == 1


@pytest.mark.asyncio
async def test_generation_cleanup_preserves_active_scope_and_other_owners(tmp_path):
    store = LanceMemoryStore(tmp_path)
    current = Scope("user'quoted", "session'quoted", 2, "current-model")
    old_epoch = replace(current, epoch=1)
    old_model = replace(current, signature="old-model")
    old_both = replace(old_model, epoch=0)
    other_user = replace(old_epoch, user_id="other")
    other_session = replace(old_model, session_id="other")
    future = replace(old_model, epoch=3)
    for scope in (current, old_epoch, old_model, old_both, other_user, other_session, future):
        vector = [1.0] if scope.signature == "old-model" else [1.0, 0.0]
        await store.upsert(scope, [_doc()], [vector])

    assert await store.prune_generations(current) == 3
    assert await store.list_document_hashes(current) == {"one": "hash-one"}
    for scope in (old_epoch, old_model, old_both):
        assert await store.list_document_hashes(scope) == {}
    for scope in (other_user, other_session, future):
        assert await store.list_document_hashes(scope) == {"one": "hash-one"}
    assert await store.prune_generations(current) == 0
    assert await store.count_template(current.user_id, "template") == 3
