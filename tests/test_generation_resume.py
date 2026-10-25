"""Saved generation requests resume in place and fence stopped workers."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures import adventure_creation
from backend.api.routes.adventures import generation_resume as resume_api
from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine import world_generator
from backend.engine.generation_control import (
    assert_generation_current,
    generation_run,
    guard_generation_write,
)
from backend.models.adventure_template import AdventureTemplate, GenerationCancelled
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def failed_adventure(client, monkeypatch):
    monkeypatch.setattr(
        adventure_creation.WorldGenerator,
        "generate_world",
        AsyncMock(side_effect=RuntimeError("Simulated provider timeout")),
    )
    response = await client.post("/api/adventures/", json={"title": "Saved world"})
    assert response.status_code == 201
    return response.json()


async def test_resume_reuses_session_and_saved_request(auth_client, monkeypatch):
    original_generator = adventure_creation.WorldGenerator.generate_world
    ids = await failed_adventure(auth_client, monkeypatch)
    status = (await auth_client.get(f"/api/adventures/{ids['adventure_id']}/status")).json()
    assert status["can_resume"] is True
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        original_run = adventure.generation_run_id
        assert adventure.generation_request["session_id"] == ids["game_id"]
        assert adventure.generation_request["payload"]["title"] == "Saved world"
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == ids["game_id"])
        )
        initial_snapshot = state.entity_states["__manifest_snapshot__"]
        assert initial_snapshot["adventure"]["is_ready"] is False
        assert initial_snapshot["original_manifest"] == {"npc_card_settings": {"show_state": False}}
        adventure.generation_checkpoint = {"results": {"outline": {"story": "saved"}}}
        await db.commit()

    generated_manifest = {"plot": "A newly generated story", "scenes": [{"id": "START"}]}

    async def successful_generator(*args, **kwargs):
        await original_generator(*args, **kwargs)
        db = kwargs["db"]
        adventure = await db.get(AdventureTemplate, kwargs["template_id"])
        adventure.original_manifest = generated_manifest
        await db.commit()

    monkeypatch.setattr(adventure_creation.WorldGenerator, "generate_world", successful_generator)
    response = await auth_client.post(f"/api/adventures/{ids['adventure_id']}/resume-generation")
    assert response.status_code == 200, response.text
    assert response.json()["game_id"] == ids["game_id"]
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        assert adventure.is_ready
        assert adventure.creation_error is None
        assert adventure.generation_run_id != original_run
        assert adventure.generation_checkpoint["results"]["outline"] == {"story": "saved"}
        assert await db.scalar(select(func.count(GameSession.id))) == 1
        assert await db.scalar(select(func.count(AdventureTemplate.id))) == 1
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == ids["game_id"])
        )
        snapshot = state.entity_states["__manifest_snapshot__"]["adventure"]
        assert snapshot["is_ready"] is True
        assert snapshot["creation_status"] == "Ready"
        assert (
            state.entity_states["__manifest_snapshot__"]["original_manifest"] == generated_manifest
        )


async def test_resume_rejects_second_request_while_job_is_claimed(auth_client, monkeypatch):
    ids = await failed_adventure(auth_client, monkeypatch)
    worker = AsyncMock()
    monkeypatch.setattr(resume_api, "run_background_generation", worker)
    url = f"/api/adventures/{ids['adventure_id']}/resume-generation"
    assert (await auth_client.post(url)).status_code == 200
    assert (await auth_client.post(url)).status_code == 409
    worker.assert_awaited_once()


async def test_resume_requires_owner(auth_client, monkeypatch):
    ids = await failed_adventure(auth_client, monkeypatch)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        adventure.owner_id = "another-user"
        await db.commit()
    response = await auth_client.post(f"/api/adventures/{ids['adventure_id']}/resume-generation")
    assert response.status_code == 404


async def test_resume_refuses_existing_gameplay(auth_client, monkeypatch):
    ids = await failed_adventure(auth_client, monkeypatch)
    async with TestSessionLocal() as db:
        db.add(ChatMessage(session_id=ids["game_id"], role="user", content="Already playing"))
        await db.commit()
    response = await auth_client.post(f"/api/adventures/{ids['adventure_id']}/resume-generation")
    assert response.status_code == 409
    assert "gameplay history" in response.json()["detail"]


async def test_cancel_invalidates_attempt_and_old_failure_cannot_overwrite(
    auth_client, monkeypatch
):
    ids = await failed_adventure(auth_client, monkeypatch)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        old_run = adventure.generation_run_id
        adventure.creation_status = "Generating outline"
        await db.commit()
    response = await auth_client.post(f"/api/adventures/{ids['adventure_id']}/cancel")
    assert response.status_code == 200
    token = generation_run.set(old_run)
    try:
        async with TestSessionLocal() as db:
            with pytest.raises(GenerationCancelled):
                await adventure_creation._record_generation_failure(
                    db, ids["adventure_id"], RuntimeError("late failure")
                )
            adventure = await db.get(AdventureTemplate, ids["adventure_id"])
            assert adventure.creation_status == "Cancelled"
            assert adventure.generation_run_id is None
    finally:
        generation_run.reset(token)


async def test_replaced_worker_cannot_write_and_snapshot_preserves_state(auth_client, monkeypatch):
    ids = await failed_adventure(auth_client, monkeypatch)
    token = generation_run.set("superseded-run")
    try:
        async with TestSessionLocal() as db:
            adventure = await db.get(AdventureTemplate, ids["adventure_id"])
            with pytest.raises(GenerationCancelled, match="replaced"):
                await assert_generation_current(db, adventure)
            snapshot = AdventureLogic.build_session_manifest_snapshot(adventure)
            assert snapshot["adventure"]["is_ready"] is False
            assert snapshot["adventure"]["creation_status"] == "Failed"
    finally:
        generation_run.reset(token)


async def test_atomic_guard_rejects_cancellation_after_worker_read(auth_client, monkeypatch):
    ids = await failed_adventure(auth_client, monkeypatch)
    async with TestSessionLocal() as old_worker:
        stale = await old_worker.get(AdventureTemplate, ids["adventure_id"])
        token = generation_run.set(stale.generation_run_id)
        try:
            async with TestSessionLocal() as new_worker:
                current = await new_worker.get(AdventureTemplate, ids["adventure_id"])
                current.generation_run_id = "newer-run"
                current.creation_status = "Resuming saved generation..."
                await new_worker.commit()
            with pytest.raises(GenerationCancelled):
                await guard_generation_write(old_worker, stale, creation_status="Failed")
            await old_worker.rollback()
            await old_worker.refresh(stale)
            assert stale.generation_run_id == "newer-run"
            assert stale.creation_status == "Resuming saved generation..."
        finally:
            generation_run.reset(token)


@pytest.mark.parametrize("helper", ["_log_image_generation", "_log_reused_asset"])
async def test_late_image_log_does_not_commit_after_cancel(auth_client, monkeypatch, helper):
    ids = await failed_adventure(auth_client, monkeypatch)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        old_run = adventure.generation_run_id
        adventure.creation_status = "Cancelled"
        adventure.generation_run_id = None
        await db.commit()
        original_logs = adventure.generation_logs
        token = generation_run.set(old_run)
        try:
            with pytest.raises(GenerationCancelled):
                await getattr(world_generator, helper)(
                    db, adventure, "late portrait", "/data/portrait.png"
                )
            await db.rollback()
            await db.refresh(adventure)
            assert adventure.generation_logs == original_logs
            assert adventure.creation_status == "Cancelled"
        finally:
            generation_run.reset(token)
