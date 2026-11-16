"""Canonical knowledge remains exact, isolated and independently portable."""

import io
import json
import logging
import zipfile
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.memory_rag import lifecycle
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.world_info import limits
from backend.engine.world_info.capacity import corpus_entry_bytes
from backend.engine.world_info.portability import export_world_info, import_world_info
from backend.engine.world_info.portable_schema import PortableWorldInfo
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_fixture import corpus, seed_corpus

__all__ = ["portrait_world"]
SID = "portrait-session"


async def seed(payload=None):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        original = await seed_corpus(db, SID, owner, payload)
        revision = await db.get(WorldInfoRevision, original["revisions"][1]["id"])
        revision.run_token = "live-run"
        revision.lease_token = "live-lease"
        revision.lease_until = 9999999999.0
        await db.commit()
        return owner, original


@pytest.mark.parametrize("prefix", ["assets/harbor", f"/data/adventures/sessions/{SID}/notes"])
@pytest.mark.parametrize("format", ["md", "json"])
async def test_real_copy_and_ads_roundtrip_remap_records_without_touching_source_text(
    auth_client, portrait_world, prefix, format
):
    content = prefix + ": Lanterns guide ships."
    if format == "json":
        content = json.dumps({"harbor": content}, ensure_ascii=False)
    owner, original = await seed(corpus(content, format))
    direct_export = await auth_client.get(f"/api/adventures/sessions/{SID}/export")
    assert direct_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(direct_export.content)) as archive:
        direct = json.loads(archive.read("session.json"))["world_info"]
    assert all(row["content"] == content for row in direct["revisions"])
    assert (
        direct["entries"][0]["facts"][0]["evidence"]
        == original["entries"][0]["facts"][0]["evidence"]
    )
    copied = await auth_client.post(f"/api/adventures/sessions/{SID}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
    assert manifest["world_info"]["revisions"][0]["content"] == content
    assert "run_token" not in json.dumps(manifest["world_info"])
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("harbor.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    imported_id = imported.json()["game_id"]
    old_ids = {row["id"] for key in ("sources", "revisions", "entries") for row in original[key]}
    async with TestSessionLocal() as db:
        for target in [copy_id, imported_id]:
            payload = await export_world_info(db, target, owner)
            assert payload["sources"][0]["current_revision"] == 2
            assert payload["sources"][0]["published_revision"] == 1
            assert all(row["content"] == content for row in payload["revisions"])
            assert {
                row["id"] for key in ("sources", "revisions", "entries") for row in payload[key]
            }.isdisjoint(old_ids)
            entries = payload["entries"]
            related = next(row for row in entries if row["relations"])
            assert related["relations"][0]["target_id"] in {row["id"] for row in entries}
            assert any(row["known_by"] == ["NPC_NEW"] for row in entries)
            replacement = next(row for row in payload["revisions"] if row["number"] == 2)
            assert replacement["status"] == "cancelled" and replacement["cursor"] == 0
            assert replacement["processing_language"] == "English"
            row = await db.get(WorldInfoRevision, replacement["id"])
            assert row.run_token is None and row.lease_token is None and row.lease_until is None
        original_entry = await db.get(WorldInfoEntry, original["entries"][0]["id"])
        original_entry.summary = "An independent correction."
        await db.commit()
        copied_entries = list(
            await db.scalars(select(WorldInfoEntry).where(WorldInfoEntry.session_id == copy_id))
        )
        assert all(row.summary == "A navigation note." for row in copied_entries)


@pytest.mark.parametrize(
    "mutation",
    [
        "checksum",
        "quote",
        "pointer",
        "batch",
        "revision",
        "relation",
        "duplicate_fact",
        "count",
        "recipient",
        "scope",
    ],
)
async def test_malformed_import_rejects_whole_corpus_without_partial_rows(
    auth_client, portrait_world, mutation
):
    owner = await _owner()
    payload = corpus()
    changes = {
        "checksum": lambda: payload["revisions"][0].update(content_hash="0" * 64),
        "quote": lambda: payload["entries"][0]["facts"][0]["evidence"][0].update(
            quote="X" * len(payload["entries"][0]["facts"][0]["evidence"][0]["quote"])
        ),
        "pointer": lambda: payload["entries"][0]["facts"][0]["evidence"][0].update(
            pointer="/foreign"
        ),
        "batch": lambda: payload["entries"][0].update(batch_index=1),
        "revision": lambda: payload["entries"][0].update(source_revision_id="foreign-revision"),
        "relation": lambda: payload["entries"][0]["relations"][0].update(target_id="foreign-entry"),
        "duplicate_fact": lambda: payload["entries"][1]["facts"][0].update(
            id=payload["entries"][0]["facts"][0]["id"]
        ),
        "count": lambda: payload["revisions"][0].update(facts_count=3),
        "recipient": lambda: payload["entries"][1].update(known_by=["ITEM_1"]),
        "scope": lambda: payload["entries"][1].update(audience="common_knowledge"),
    }
    changes[mutation]()
    for row in payload["entries"]:
        draft = EntryDraft.model_validate({key: row[key] for key in EntryDraft.model_fields})
        row["content_hash"] = entry_hash(draft)
    async with TestSessionLocal() as db:
        with pytest.raises(ValueError):
            await import_world_info(db, payload, SID, owner)
        assert await db.scalar(select(WorldInfoSource.id)) is None


async def _owner():
    async with TestSessionLocal() as db:
        return await db.scalar(select(User.id))


async def test_owned_helpers_reject_foreign_session_even_with_same_npc_id(
    auth_client, portrait_world
):
    owner, _ = await seed()
    async with TestSessionLocal() as db:
        with pytest.raises(ValueError, match="session not found"):
            await export_world_info(db, "other-session", owner)
        with pytest.raises(ValueError, match="session not found"):
            await import_world_info(db, corpus(), "other-session", owner)
        npc = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == SID, WorldEntity.id == "NPC_NEW")
        )
        await db.delete(npc)
        await db.flush()
        await db.execute(
            WorldInfoSource.__table__.delete().where(WorldInfoSource.session_id == SID)
        )
        with pytest.raises(ValueError, match="outside the destination"):
            await import_world_info(db, corpus(), SID, owner)


async def test_replay_retains_current_world_info_outside_gameplay_timeline(
    auth_client, portrait_world
):
    owner, original = await seed()
    async with TestSessionLocal() as db:
        before = await capture(db, SID)
        entry = await db.get(WorldInfoEntry, original["entries"][0]["id"])
        entry.summary = "A later author correction."
        entry.edited = True
        draft = EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
        entry.search_text = searchable_text(draft)
        entry.content_hash = entry_hash(draft)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        state.in_game_time += 10
        await db.commit()
        await restore(db, SID, before)
        await db.commit()
        entry = await db.get(WorldInfoEntry, original["entries"][0]["id"])
        assert entry.summary == "A later author correction." and entry.edited is True
        assert len(list(await db.scalars(select(WorldInfoRevision)))) == 2
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        assert state.in_game_time == before["state"]["in_game_time"]


async def test_template_delete_retains_lore_and_session_delete_purges_it(
    auth_client, portrait_world, monkeypatch
):
    await seed()
    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.cleanup_adventure_assets", AsyncMock()
    )
    monkeypatch.setattr(lifecycle.LanceMemoryStore, "delete_session", AsyncMock(return_value=0))
    assert (await auth_client.delete("/api/adventures/portrait-template")).status_code == 200
    async with TestSessionLocal() as db:
        assert (await db.get(GameSession, SID)).template_id is None
        assert len(list(await db.scalars(select(WorldInfoSource)))) == 1
        assert len(list(await db.scalars(select(WorldInfoEntry)))) == 2
    assert (await auth_client.delete(f"/api/adventures/sessions/{SID}")).status_code == 200
    async with TestSessionLocal() as db:
        for model in (WorldInfoSource, WorldInfoRevision, WorldInfoEntry):
            assert await db.scalar(select(model.id)) is None


async def test_actual_checkpoint_restore_retains_new_author_edits_and_source_revisions(
    auth_client, portrait_world
):
    owner, original = await seed()
    async with TestSessionLocal() as db:
        checkpoint = await SessionCheckpointService.create_checkpoint(db, SID, "manual")
        checkpoint_id = checkpoint.id
        entry = await db.get(WorldInfoEntry, original["entries"][0]["id"])
        entry.summary = "A correction made after the checkpoint."
        entry.edited = True
        entry.version += 1
        draft = EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
        entry.search_text, entry.content_hash = searchable_text(draft), entry_hash(draft)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        state.in_game_time = 600
        await db.commit()
        authored = await export_world_info(db, SID, owner)
    restored = await auth_client.post(
        f"/api/adventures/sessions/{SID}/checkpoints/{checkpoint_id}/restore"
    )
    assert restored.status_code == 200, restored.text
    async with TestSessionLocal() as db:
        assert await export_world_info(db, SID, owner) == authored
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        assert state.in_game_time == 480


async def test_rejected_ads_does_not_log_raw_source_validation_input(
    auth_client, portrait_world, caplog
):
    await seed()
    exported = await auth_client.get(f"/api/adventures/sessions/{SID}/export")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
    marker = "fixture-lore"
    manifest["world_info"]["revisions"][0]["content"] = marker + "\x00"
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("session.json", json.dumps(manifest))
    with caplog.at_level(logging.ERROR):
        imported = await auth_client.post(
            "/api/adventures/sessions/import",
            files={"file": ("invalid-source.ads", bundle.getvalue(), "application/zip")},
        )
    assert imported.status_code == 400
    assert marker not in caplog.text


def test_legacy_absent_section_is_empty_and_input_is_not_rewritten():
    assert PortableWorldInfo.model_validate({}).sources == []
    payload = corpus()
    original = deepcopy(payload)
    PortableWorldInfo.model_validate(payload)
    assert payload == original


async def test_import_reassigns_ownership_and_does_not_replace_existing_corpus(
    auth_client, portrait_world
):
    owner = await _owner()
    payload = corpus()
    for key in ("sources", "revisions", "entries"):
        for row in payload[key]:
            row.update(user_id="foreign-owner", session_id="other-session")
    async with TestSessionLocal() as db:
        await import_world_info(db, payload, SID, owner)
        await db.commit()
        for model in (WorldInfoSource, WorldInfoRevision, WorldInfoEntry):
            rows = list(await db.scalars(select(model)))
            assert rows and all(row.user_id == owner and row.session_id == SID for row in rows)
        before = await export_world_info(db, SID, owner)
        with pytest.raises(ValueError, match="destination must be empty"):
            await import_world_info(db, corpus(), SID, owner)
        assert await export_world_info(db, SID, owner) == before


@pytest.mark.parametrize("value", [True, "1", 0, 2])
def test_portable_version_rejects_coercion_and_unknown_versions(value):
    with pytest.raises(ValueError):
        PortableWorldInfo.model_validate({"version": value})


@pytest.mark.parametrize("value", ["en", "Unknown", " English ", ""])
def test_processing_language_requires_a_supported_normalized_snapshot(value):
    payload = corpus()
    payload["revisions"][0]["processing_language"] = value
    with pytest.raises(ValueError):
        PortableWorldInfo.model_validate(payload)


@pytest.mark.parametrize(
    "status,cursor", [("queued", 0), ("processing", 0), ("review", 1), ("cancelled", 1)]
)
def test_progressed_jobs_require_frozen_processing_language(status, cursor):
    payload = corpus()
    payload["revisions"][0].update(status=status, cursor=cursor, processing_language=None)
    with pytest.raises(ValueError, match="frozen content language"):
        PortableWorldInfo.model_validate(payload)


def test_saved_entries_cannot_occupy_an_unprocessed_job_batch():
    payload = corpus()
    payload["revisions"][0].update(cursor=0, processed_characters=0, status="processing")
    with pytest.raises(ValueError, match="unprocessed batch"):
        PortableWorldInfo.model_validate(payload)


def test_saved_processing_character_count_matches_completed_source_batches():
    payload = corpus()
    payload["revisions"][0]["processed_characters"] -= 1
    with pytest.raises(ValueError, match="processing character count"):
        PortableWorldInfo.model_validate(payload)


def test_json_numeric_source_can_have_more_decoded_processing_characters_than_input():
    payload = corpus("1e2", "json")
    assert payload["revisions"][0]["input_characters"] == 3
    assert payload["revisions"][0]["processed_characters"] == 5
    PortableWorldInfo.model_validate(payload)


async def test_import_checks_shared_byte_budget_after_host_identity_remapping(
    auth_client, portrait_world, monkeypatch
):
    payload = corpus()
    source_id = payload["sources"][0]["id"]
    revision_ids = {row["id"]: f"r{index}" for index, row in enumerate(payload["revisions"])}
    entry_ids = {row["id"]: f"e{index}" for index, row in enumerate(payload["entries"])}
    payload["sources"][0]["id"] = "s"
    for row in payload["revisions"]:
        row.update(id=revision_ids[row["id"]], source_id="s")
    for index, row in enumerate(payload["entries"]):
        assert row["source_id"] == source_id
        row.update(
            id=entry_ids[row["id"]],
            source_id="s",
            source_revision_id=revision_ids[row["source_revision_id"]],
        )
        row["facts"][0]["id"] = f"f{index}"
        for relation in row["relations"]:
            relation["target_id"] = entry_ids[relation["target_id"]]
        draft = EntryDraft.model_validate({key: row[key] for key in EntryDraft.model_fields})
        row["content_hash"] = entry_hash(draft)
    parsed = PortableWorldInfo.model_validate(payload)
    monkeypatch.setattr(limits, "MAX_SESSION_ENTRY_BYTES", corpus_entry_bytes(parsed.entries))
    owner = await _owner()
    async with TestSessionLocal() as db:
        with pytest.raises(ValueError, match="storage budget"):
            await import_world_info(db, payload, SID, owner)
        assert await db.scalar(select(WorldInfoSource.id)) is None
