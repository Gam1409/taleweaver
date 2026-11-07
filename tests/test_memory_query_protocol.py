"""Embedding input roles and Unicode fallback preserve the actual search request."""

import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from backend.engine.memory_rag import embeddings, retrieval
from backend.engine.memory_rag.recall_sources import _message_ids
from backend.engine.memory_rag.settings import MemoryRagSettings, embedding_signature
from backend.engine.memory_rag.store_schema import lexical_filter
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_memory_rag_embeddings_store import _mock_transport, _user
from tests.test_npc_journal import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("value", [None, 7, "", "   "])
async def test_embedding_prefix_cannot_mask_invalid_raw_text(monkeypatch, value):
    remote = AsyncMock()
    monkeypatch.setattr(embeddings, "_embed", remote)
    settings = MemoryRagSettings(
        enabled=True, base_url="http://localhost:11434", model="embed", query_prefix="query: "
    )
    with pytest.raises(embeddings.EmbeddingError, match="input"):
        await embeddings.embed_with_settings(settings, [value], purpose="query")
    remote.assert_not_awaited()


def test_transcript_search_folds_a_long_row_once(monkeypatch):
    from backend.utils import sqlite_text

    folded = []
    original = sqlite_text.casefold

    def track(value):
        folded.append(value)
        return original(value)

    monkeypatch.setattr(sqlite_text, "casefold", track)
    text = "Ordinary scene. " * 1000 + "ВАЗА в посольстве"
    assert sqlite_text.contains_any(text, json.dumps(["колба", "ваза", "образец"])) == 1
    assert folded == [text]
    assert sqlite_text.contains_any(None, json.dumps(["ваза"])) == 0


async def test_query_and_document_prefixes_are_distinct_and_keep_exact_whitespace(monkeypatch):
    user = _user()
    user.llm_settings["memory_rag"].update(query_prefix="query: ", document_prefix="passage: ")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["input"])
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    _mock_transport(monkeypatch, handler)
    await embeddings.embed_texts(user, ["Где проба?"], purpose="query")
    await embeddings.embed_texts(user, ["Проба в колбе."])
    assert sent == [["query: Где проба?"], ["passage: Проба в колбе."]]


def test_default_signature_stays_compatible_and_prefix_changes_separate_vector_spaces():
    settings = MemoryRagSettings(base_url="http://localhost:11434", model="embed")
    old = hashlib.sha256(
        json.dumps(
            [settings.provider, settings.base_url, settings.model, 2], separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert embedding_signature(settings, 2) == old
    query = settings.model_copy(update={"query_prefix": "query: "})
    document = settings.model_copy(update={"document_prefix": "passage: "})
    assert len({old, embedding_signature(query, 2), embedding_signature(document, 2)}) == 3


def test_lexical_filter_keeps_the_first_explicit_search_term():
    query = "ваза " + " ".join("аа" + str(i) for i in range(40))
    assert "ваза" in lexical_filter(query)


async def test_old_russian_source_is_found_after_it_leaves_the_recent_window(portrait_world):
    base = datetime(2026, 1, 1)
    async with TestSessionLocal() as db:
        old = ChatMessage(
            session_id="portrait-session",
            role="assistant",
            content="РИН получила ВАЗУ.",
            created_at=base,
        )
        db.add(old)
        db.add_all(
            [
                ChatMessage(
                    session_id="portrait-session",
                    role="assistant",
                    content=f"Other event {i}.",
                    created_at=base + timedelta(seconds=i + 1),
                )
                for i in range(90)
            ]
        )
        await db.commit()
        ids = await _message_ids(db, "portrait-session", "рин ваза", [])
        assert old.id in ids
        assert (
            await db.scalar(select(ChatMessage.content).where(ChatMessage.id == old.id))
            == old.content
        )


async def test_foreground_query_uses_query_encoding_and_a_short_deadline(monkeypatch):
    user = _user()
    embed = AsyncMock(return_value=[[1.0, 0.0]])
    monkeypatch.setattr(retrieval, "embed_texts", embed)
    settings = MemoryRagSettings(
        enabled=True, timeout_seconds=60, base_url="http://localhost:11434", model="test-embed"
    )
    from types import SimpleNamespace

    from backend.engine.memory_rag.store import Scope

    # Wrong dimension signature returns before any store access.
    await retrieval._query_vectors(
        SimpleNamespace(user=user), "Где проба?", Scope("u", "s", 0, "different"), settings
    )
    assert embed.call_args.kwargs["purpose"] == "query"
    assert embed.call_args.kwargs["timeout"] <= 2
