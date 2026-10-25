"""Public cards, save portability, rewind safety and failure recovery."""

import asyncio
import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.npc_journal import portraits, worker
from backend.engine.npc_journal.lifecycle import rewind_journals
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.schema import CharacterObservation, JournalExtraction
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import (
    apply,
    introduction,
    journal_world,
    npc_by_id,
    observation,
    portrait_world,
    save_message,
)

__all__ = ["journal_world", "portrait_world"]


async def seed_character():
    message_id = await save_message()
    npc_id = (await apply(message_id, [introduction(observations=[observation()])]))[0]
    return message_id, npc_id


async def test_card_api_directory_history_and_off_scene_access(auth_client, journal_world):
    _, npc_id = await seed_character()
    directory = await auth_client.get("/api/adventures/portrait-session/npcs")
    assert directory.status_code == 200
    assert npc_id in [item["id"] for item in directory.json()["characters"]]
    details = await auth_client.get(f"/api/adventures/portrait-session/npcs/{npc_id}")
    assert details.json()["entries"][0]["text"] == "Синий плащ"
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.current_scene_id = "FOREST"
        await db.commit()
    directory = await auth_client.get("/api/adventures/portrait-session/npcs")
    assert [item["id"] for item in directory.json()["characters"]] == [npc_id]
    assert (
        await auth_client.get(f"/api/adventures/portrait-session/npcs/{npc_id}")
    ).status_code == 200


@pytest.mark.parametrize(
    "path", ["other-session/npcs", "other-session/npcs/NPC_NEW", "missing/npcs"]
)
async def test_cards_do_not_expose_foreign_saves(auth_client, journal_world, path):
    assert (await auth_client.get(f"/api/adventures/{path}")).status_code == 404


async def test_hidden_npc_does_not_leak_through_directory(auth_client, journal_world):
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.is_hidden = True
        await db.commit()
    response = await auth_client.get("/api/adventures/portrait-session/npcs/NPC_NEW")
    assert response.status_code == 404


async def test_learned_character_stays_known_without_revealing_hidden_items(
    auth_client, journal_world
):
    _, npc_id = await seed_character()
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == npc_id
            )
        )
        npc.is_hidden = True
        npc.inventory = [{"id": "secret_key", "name": "Secret key"}]
        await db.commit()
    response = await auth_client.get(f"/api/adventures/portrait-session/npcs/{npc_id}")
    assert response.status_code == 200
    assert response.json()["scene_id"] is None
    assert "inventory" not in response.json()
    assert response.json()["entries"][0]["text"] == "Синий плащ"


async def test_failed_introduction_pauses_later_learning_until_retry(journal_world, monkeypatch):
    owner, _ = journal_world
    first = await save_message()
    later = await save_message("Мира сказала: «Я кузнец».")
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, first)
        message.npc_journal = {"status": "failed", "attempts": 1}
        await db.commit()
    extract_mock = AsyncMock()
    monkeypatch.setattr(worker, "extract", extract_mock)
    monkeypatch.setattr(worker, "resume_pending", AsyncMock())
    await worker._run("portrait-session", owner)
    extract_mock.assert_not_called()
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, later)).npc_journal["status"] == "pending"


async def test_export_import_preserves_journal_and_remaps_source_message_ids(
    auth_client, journal_world
):
    original_message, npc_id = await seed_character()
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, original_message)
        message.npc_journal = {"status": "done"}
        await db.commit()
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
        entity = next(e for e in manifest["world_entities"] if e["id"] == npc_id)
        assert entity["metadata_json"]["npc_journal"]["entries"]
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("session.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    new_id = imported.json()["game_id"]
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == new_id, WorldEntity.id == npc_id)
        )
        journal = journal_of(npc)
        assert journal["introduced_message_id"] != original_message
        restored = await db.get(ChatMessage, journal["introduced_message_id"])
        assert restored.session_id == new_id and restored.scene_id == "TOWER"
        assert restored.npc_journal["status"] == "done"
        assert journal["entries"][0]["message_id"] == restored.id


async def test_rewind_removes_future_characters_and_later_facts(journal_world):
    message_id, npc_id = await seed_character()
    later = await save_message("Мира сказала: «Я кузнец».")
    await apply(
        later,
        [
            CharacterObservation(
                name="Мира",
                npc_id=npc_id,
                observations=[observation("background", "Кузнец", "Я кузнец", topic="occupation")],
            )
        ],
    )
    async with TestSessionLocal() as db:
        await rewind_journals(db, "portrait-session", [later])
        await db.commit()
    assert len(journal_of(await npc_by_id(npc_id))["entries"]) == 1
    async with TestSessionLocal() as db:
        await rewind_journals(db, "portrait-session", [message_id])
        await db.commit()
    assert await npc_by_id(npc_id) is None


async def test_real_checkpoint_restore_removes_introduced_npc(journal_world):
    async with TestSessionLocal() as db:
        checkpoint = await SessionCheckpointService.create_checkpoint(
            db, "portrait-session", "manual"
        )
        await db.commit()
        checkpoint_id = checkpoint.id
    message_id, npc_id = await seed_character()
    async with TestSessionLocal() as db:
        assert (
            await SessionCheckpointService.restore_checkpoint(db, "portrait-session", checkpoint_id)
            == 1
        )
        await db.commit()
        assert await db.get(ChatMessage, message_id) is None
    assert await npc_by_id(npc_id) is None


async def test_copy_keeps_identity_and_remaps_journal_evidence(auth_client, journal_world):
    message_id, npc_id = await seed_character()
    response = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
    assert response.status_code == 201, response.text
    copied_id = response.json()["game_id"]
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == copied_id, WorldEntity.id == npc_id)
        )
        assert npc is not None
        journal = journal_of(npc)
        assert journal["introduced_message_id"] != message_id
        message = await db.get(ChatMessage, journal["introduced_message_id"])
        assert message.session_id == copied_id and message.scene_id == "TOWER"
        assert journal["entries"][0]["message_id"] == message.id


async def test_extraction_timeout_is_recoverable(journal_world, monkeypatch, auth_client):
    owner, _ = journal_world
    message_id = await save_message()
    cancelled = asyncio.Event()

    async def slow(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker, "EXTRACTION_TIMEOUT", 0.02)
    monkeypatch.setattr(worker, "extract", slow)
    assert not await worker.process_message(message_id, owner)
    assert cancelled.is_set()
    response = await auth_client.get("/api/adventures/portrait-session/npcs")
    assert response.json()["failed"] == 1
    assert (await auth_client.post("/api/adventures/portrait-session/npc-journal/retry")).json()[
        "queued"
    ] == 1
    monkeypatch.setattr(
        worker, "extract", AsyncMock(return_value=JournalExtraction(characters=[introduction()]))
    )
    assert await worker.process_message(message_id, owner)


async def test_deleted_narration_discards_late_extraction(journal_world, monkeypatch):
    owner, portraits_mock = journal_world
    message_id = await save_message()

    async def delete_during_extraction(*args):
        async with TestSessionLocal() as db:
            await db.delete(await db.get(ChatMessage, message_id))
            await db.commit()
        return JournalExtraction(characters=[introduction()])

    monkeypatch.setattr(worker, "extract", delete_during_extraction)
    await worker.process_message(message_id, owner)
    portraits_mock.assert_not_called()


async def test_portrait_failure_preserves_character_and_history(journal_world, monkeypatch):
    owner, _ = journal_world
    _, npc_id = await seed_character()
    monkeypatch.setattr(
        portraits, "regenerate_session_portrait", AsyncMock(side_effect=RuntimeError("offline"))
    )
    await portraits._run("portrait-session", npc_id, owner)
    npc = await npc_by_id(npc_id)
    assert journal_of(npc)["portrait_status"] == "failed"
    assert journal_of(npc)["entries"] and npc.name == "Мира"
