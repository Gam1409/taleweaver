"""Memory configuration and clearing remain independent of canonical game data."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.api.routes import memory_index, memory_settings
from backend.core.security import encryption_util
from backend.engine.memory_rag import worker
from backend.models.adventure_template import AdventureTemplate
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
CONFIG = {
    "enabled": True,
    "provider": "openai",
    "base_url": "http://localhost:8001",
    "model": "multilingual-embed",
    "timeout_seconds": 10,
}
BASE = "/api/adventures/templates/portrait-template/memory-index"


async def test_vault_manages_the_existing_embedding_credential(auth_client, monkeypatch):
    embed = AsyncMock(return_value=[[0.1]])
    monkeypatch.setattr(memory_settings, "embed_with_settings", embed)
    await auth_client.put("/api/settings/memory-rag", json={**CONFIG, "api_key": "first"})
    status = await auth_client.get("/api/settings", params={"include_available_constants": False})
    assert status.json()["keys"]["memory_embeddings"] == {"masked": "********", "is_env": False}
    updated = await auth_client.post(
        "/api/settings/keys", json={"provider": "memory_embeddings", "api_key": "replacement"}
    )
    assert updated.status_code == 200
    await auth_client.post("/api/settings/memory-rag/test", json=CONFIG)
    assert embed.await_args.kwargs["api_key"] == "replacement"
    assert (await auth_client.delete("/api/settings/keys/memory_embeddings")).status_code == 200
    assert not (await auth_client.get("/api/settings/memory-rag")).json()["key_configured"]


async def test_settings_save_keeps_secret_and_legacy_llm_save_keeps_memory(auth_client):
    response = await auth_client.put(
        "/api/settings/memory-rag", json={**CONFIG, "api_key": "test-secret"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["key_configured"] is True
    assert "test-secret" not in response.text
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        assert user.llm_settings["small_model"] == "llama3.2"
        assert (
            encryption_util.decrypt_key(user.encrypted_api_keys["memory_embeddings"])
            == "test-secret"
        )
    response = await auth_client.post(
        "/api/settings/llm",
        json={
            "small_model": "llama3.2",
            "small_model_provider": "ollama",
            "complex_model": "qwen2.5",
            "complex_model_provider": "ollama",
            "preferred_provider": "ollama",
        },
    )
    assert response.status_code == 200, response.text
    saved = (await auth_client.get("/api/settings/memory-rag")).json()
    assert saved["model"] == CONFIG["model"] and saved["enabled"] is True
    assert (await auth_client.put("/api/settings/memory-rag", json=CONFIG)).json()[
        "key_configured"
    ] is True


async def test_connection_test_does_not_save_draft_or_expose_credentials(auth_client, monkeypatch):
    embed = AsyncMock(return_value=[[0.25, 0.75]])
    monkeypatch.setattr(memory_settings, "embed_with_settings", embed)
    response = await auth_client.post(
        "/api/settings/memory-rag/test", json={**CONFIG, "api_key": "test-secret"}
    )
    assert response.status_code == 200 and response.json()["dimensions"] == 2
    assert embed.await_args.kwargs["api_key"] == "test-secret"
    assert "test-secret" not in response.text
    saved = (await auth_client.get("/api/settings/memory-rag")).json()
    assert saved["enabled"] is False and saved["key_configured"] is False


async def test_enabled_requires_complete_embedding_settings(auth_client):
    response = await auth_client.put("/api/settings/memory-rag", json={"enabled": True})
    assert response.status_code == 422


async def test_clear_pauses_only_owned_adventure_sessions_preserving_history(
    auth_client, portrait_world, monkeypatch
):
    store = AsyncMock()
    monkeypatch.setattr(memory_index, "LanceMemoryStore", lambda: store)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.world_memories = [{"description": "A promise remains.", "scope": "global"}]
        before = deepcopy(state.entity_states)
        db.add(
            MemoryIndexState(
                session_id="other-session",
                user_id="another-owner",
                template_id="portrait-template",
                epoch=4,
                desired_revision=8,
                indexed_revision=8,
                paused=False,
                status="ready",
            )
        )
        await db.commit()
    response = await auth_client.delete(BASE)
    assert response.status_code == 200 and response.json() == {
        "cleared": True,
        "session_count": 1,
        "paused": True,
    }
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        own = await db.get(MemoryIndexState, "portrait-session")
        other = await db.get(MemoryIndexState, "other-session")
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert own.paused is True and own.epoch == 1 and own.lease_token is None
        assert other.epoch == 4 and other.paused is False
        assert state.entity_states == before
        assert state.world_memories[0]["description"] == "A promise remains."
        store.delete_template.assert_awaited_once_with(user.id, "portrait-template")


async def test_foreign_template_cannot_be_cleared(auth_client, portrait_world, monkeypatch):
    store = AsyncMock()
    monkeypatch.setattr(memory_index, "LanceMemoryStore", lambda: store)
    async with TestSessionLocal() as db:
        db.add(AdventureTemplate(id="foreign-template", title="Foreign", owner_id="another-owner"))
        await db.commit()
    response = await auth_client.delete("/api/adventures/templates/foreign-template/memory-index")
    assert response.status_code == 404
    store.delete_template.assert_not_awaited()


async def test_rebuild_requires_settings_and_explicitly_resumes_index(
    auth_client, portrait_world, monkeypatch
):
    store = AsyncMock()
    monkeypatch.setattr(memory_index, "LanceMemoryStore", lambda: store)
    schedule = []
    monkeypatch.setattr(memory_index, "schedule_rows", lambda rows, **kw: schedule.extend(rows))
    assert (await auth_client.post(BASE + "/rebuild")).status_code == 400
    await auth_client.put("/api/settings/memory-rag", json=CONFIG)
    await auth_client.delete(BASE)
    response = await auth_client.post(BASE + "/rebuild")
    assert response.status_code == 200 and response.json()["session_count"] == 1
    assert len(schedule) == 1 and schedule[0].paused is False
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        assert row.epoch >= 2 and row.signature is None


async def test_clear_failure_still_invalidates_inflight_epoch(
    auth_client, portrait_world, monkeypatch
):
    store = AsyncMock()
    store.delete_template.side_effect = OSError("private/path should not escape")
    monkeypatch.setattr(memory_index, "LanceMemoryStore", lambda: store)
    response = await auth_client.delete(BASE)
    assert response.status_code == 503 and "private/path" not in response.text
    async with TestSessionLocal() as db:
        assert (await db.get(MemoryIndexState, "portrait-session")).paused is True


async def test_embedding_change_fences_all_users_but_does_not_unpause_cleared_index(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=user.id,
                template_id="portrait-template",
                epoch=2,
                desired_revision=5,
                indexed_revision=5,
                paused=True,
                status="paused",
                signature="old-space",
                lease_token="inflight",
                lease_until=9999999999,
            )
        )
        await db.commit()
    assert (await auth_client.put("/api/settings/memory-rag", json=CONFIG)).status_code == 200
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        assert row.epoch == 3 and row.paused is True
        assert row.signature is None and row.lease_token is None


async def test_timeout_only_change_preserves_index_generation_and_inflight_claim(
    auth_client, portrait_world, monkeypatch
):
    monkeypatch.setattr("backend.engine.memory_rag.worker.schedule", Mock())
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.llm_settings = {**user.llm_settings, "memory_rag": CONFIG}
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=user.id,
                template_id="portrait-template",
                epoch=2,
                desired_revision=5,
                indexed_revision=5,
                status="ready",
                signature="existing-vector-space",
                lease_token="inflight",
                lease_until=9999999999,
            )
        )
        await db.commit()
    response = await auth_client.put(
        "/api/settings/memory-rag", json={**CONFIG, "timeout_seconds": 30}
    )
    assert response.status_code == 200 and response.json()["timeout_seconds"] == 30
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        assert row.epoch == 2 and row.signature == "existing-vector-space"
        assert row.desired_revision == row.indexed_revision == 5
        assert row.lease_token == "inflight" and row.status == "ready"


@pytest.mark.parametrize(
    "url,method,change",
    [
        ("/api/settings/keys", "POST", {"provider": "memory_embeddings", "api_key": "new"}),
        ("/api/settings/keys/memory_embeddings", "DELETE", None),
        ("/api/settings/memory-rag", "PUT", {**CONFIG, "clear_api_key": True}),
        ("/api/settings/memory-rag", "PUT", {**CONFIG, "api_key": "new"}),
    ],
)
async def test_ready_index_stays_idle_on_credential_edit(
    auth_client, portrait_world, monkeypatch, url, method, change
):
    schedule = Mock()
    monkeypatch.setattr(worker, "schedule", schedule)
    await auth_client.put("/api/settings/memory-rag", json={**CONFIG, "api_key": "original"})
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        row.indexed_revision = row.desired_revision
        row.signature = "existing-space"
        row.status = "ready"
        expected = row.epoch, row.desired_revision
        await db.commit()

    schedule.reset_mock()
    assert (await auth_client.request(method, url, json=change)).status_code == 200
    schedule.assert_called_once_with("other-session", "another-owner")
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        assert (row.epoch, row.indexed_revision) == (row.epoch, row.desired_revision) == expected
        assert row.signature == "existing-space" and row.status == "ready"


async def test_rotation_retries_partial_index_and_fences_stale_batch(
    auth_client, portrait_world, monkeypatch
):
    from backend.engine.memory_rag import maintenance

    schedule = Mock()
    monkeypatch.setattr(worker, "schedule", schedule)
    await auth_client.put("/api/settings/memory-rag", json=CONFIG)
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        other = await db.get(MemoryIndexState, "other-session")
        other.paused = True
        row.signature = "partial-space"
        row.status = "indexing"
        owner, epoch = row.user_id, row.epoch
        await db.commit()
    claim = await worker._claim("portrait-session", owner)
    cycle = maintenance.cycle("portrait-session", owner, epoch)
    cycle.failures = {"index": (1, 1e12), "summary": (2, 1e12)}
    schedule.reset_mock()
    response = await auth_client.post(
        "/api/settings/keys", json={"provider": "memory_embeddings", "api_key": "replacement"}
    )
    assert response.status_code == 200
    schedule.assert_called_once_with("portrait-session", owner)
    assert not await worker._write_batch(claim, "partial-space", [], [])
    assert maintenance.cycle("portrait-session", owner, epoch).failures == {"summary": (2, 1e12)}
    fresh = await worker._claim("portrait-session", owner)
    assert fresh.signature == "partial-space" and fresh.epoch == claim.epoch
    assert fresh.revision == claim.revision and fresh.token != claim.token


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "ollama"},
        {"model": "another-model"},
        {"base_url": "http://localhost:8002"},
        {"document_prefix": "passage: "},
        {"query_prefix": "query: "},
    ],
)
async def test_space_change_rejects_previous_worker(
    auth_client, portrait_world, monkeypatch, change
):
    monkeypatch.setattr(worker, "schedule", Mock())
    await auth_client.put("/api/settings/memory-rag", json=CONFIG)
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        owner = row.user_id
        row.signature = "old-space"
        await db.commit()
    claim = await worker._claim("portrait-session", owner)
    response = await auth_client.put("/api/settings/memory-rag", json={**CONFIG, **change})
    assert response.status_code == 200
    assert not await worker._write_batch(claim, "old-space", [], [])
    fresh = await worker._claim("portrait-session", owner)
    assert fresh.epoch > claim.epoch and fresh.signature is None


async def test_disabling_fences_worker_and_resume_keeps_committed_vectors(
    auth_client, portrait_world, monkeypatch
):
    schedule = Mock()
    monkeypatch.setattr(worker, "schedule", schedule)
    await auth_client.put("/api/settings/memory-rag", json=CONFIG)
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        row.signature = "partial-space"
        owner = row.user_id
        await db.commit()
    claim = await worker._claim("portrait-session", owner)
    schedule.reset_mock()
    response = await auth_client.put("/api/settings/memory-rag", json={**CONFIG, "enabled": False})
    assert response.status_code == 200
    schedule.assert_not_called()
    assert not await worker._write_batch(claim, "partial-space", [], [])
    response = await auth_client.put("/api/settings/memory-rag", json=CONFIG)
    assert response.status_code == 200
    schedule.assert_any_call("portrait-session", owner)
    fresh = await worker._claim("portrait-session", owner)
    assert fresh.epoch == claim.epoch and fresh.signature == "partial-space"
    assert fresh.revision == claim.revision
