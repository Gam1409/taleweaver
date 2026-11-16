"""Illustration receipts survive session forks, portable saves and history restores."""

import asyncio
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from backend.engine.npc_journal.messages import copy_messages, restore_messages
from backend.engine.scene_illustrations.context import illustration_status
from backend.engine.scene_illustrations.generation import _try_attach
from backend.engine.scene_illustrations.snapshots import (
    REGISTRY_KEY,
    capture_scene_snapshot,
    content_hash,
    registry_of,
)
from backend.engine.session_exporter import localize_session_paths
from backend.engine.session_importer import restore_session_paths
from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.visual_plan_lifecycle import KEY as CACHE_KEY
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.utils.path_security import data_url_to_local_path, safe_data_path
from tests.conftest import TestSessionLocal
from tests.test_legacy_session_bundle import bundle
from tests.test_session_portraits import portrait_world

__all__ = ["bundle", "portrait_world"]

SESSION_ID = "portrait-session"
MESSAGE_ID = "illustrated-reply"
IMAGE_URL = f"/data/adventures/sessions/{SESSION_ID}/visuals/illustrations/moment.png"


@pytest.fixture
def generation_details():
    """Include path-shaped query text and IDs that are historical evidence, not links."""
    return {
        "provider": "comfyui",
        "model": "scene-checkpoint.safetensors",
        "workflow": "saved-workflow",
        "seed": 0,
        "width": 768,
        "height": 512,
        "positive_prompt": "Лина у окна. A quiet evening.",
        "negative_prompt": "",
        "sampler": "euler",
        "steps": 23,
        "cfg": 5.5,
        "visual_plan": {"plan_hash": "saved-plan-hash", "audit": {"status": "passed"}},
        "queries": [
            {
                "operation": "Visual prompt",
                "model": "utility-model",
                "system_prompt": f"Keep the source marker {MESSAGE_ID} unchanged.",
                "user_prompt": IMAGE_URL,
                "response": "assets/reference.png",
                "truncated": False,
            }
        ],
        "future_metadata": {"values": [None, False, 0, ""]},
    }


@pytest_asyncio.fixture
async def illustrated_save(portrait_world, generation_details):
    path = Path(safe_data_path("adventures", "sessions", SESSION_ID, "visuals", "illustrations"))
    await asyncio.to_thread(path.mkdir, parents=True)
    Image.new("RGB", (24, 16), "blue").save(path / "moment.png")
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = "vn"
        game = await db.get(GameSession, SESSION_ID)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION_ID))
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {"adventure": {"rule_enforcement_mode": "vn"}},
        }
        message = ChatMessage(
            id=MESSAGE_ID,
            session_id=SESSION_ID,
            role="assistant",
            content="Лина остановилась у окна.",
            scene_id="TOWER",
            sequence_id="chapter-two",
        )
        db.add(message)
        await db.flush()
        await capture_scene_snapshot(db, state, message, {"setting": "A quiet evening"})
        snapshot = registry_of(state.entity_states)["snapshots"][message.id]
        assert await _try_attach(
            db, SESSION_ID, message.id, game.user_id, snapshot, IMAGE_URL, generation_details
        )
        await db.refresh(state)
        state.entity_states = {
            **state.entity_states,
            CACHE_KEY: {"entries": {"stale": {"message_id": MESSAGE_ID}}},
        }
        await db.commit()


async def saved_rows(session_id):
    async with TestSessionLocal() as db:
        message = await db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id))
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        return message, state


@pytest.mark.parametrize(
    "value",
    ["missing", None, {}, {"image_url": IMAGE_URL, "content_hash": "legacy-hash"}],
    ids=["missing", "null", "empty", "legacy-image"],
)
async def test_restore_accepts_legacy_and_empty_illustrations(portrait_world, value):
    raw = {"id": MESSAGE_ID, "role": "assistant", "content": "Earlier narration."}
    if value != "missing":
        raw["illustration"] = value
    async with TestSessionLocal() as db:
        ids = restore_messages(db, SESSION_ID, [raw])
        await db.flush()
        restored = await db.get(ChatMessage, ids[MESSAGE_ID])
        assert restored.illustration == (None if value == "missing" else value)


async def test_restore_detaches_nested_receipt_from_import_payload(
    portrait_world, generation_details
):
    receipt = {"image_url": IMAGE_URL, "generation_details": deepcopy(generation_details)}
    raw = {"id": MESSAGE_ID, "role": "assistant", "content": "Earlier.", "illustration": receipt}
    async with TestSessionLocal() as db:
        ids = restore_messages(db, SESSION_ID, [raw])
        restored = next(row for row in db.new if isinstance(row, ChatMessage))
        assert restored.id == ids[MESSAGE_ID]
        assert restored.illustration == receipt
        restored.illustration["generation_details"]["queries"][0]["response"] = "Changed"
        assert receipt["generation_details"] == generation_details


@pytest.mark.parametrize("receipt", [True, 17, "unknown receipt", ["future", "data"]])
async def test_unknown_receipt_shape_is_retained_without_breaking_status(portrait_world, receipt):
    raw = {"id": MESSAGE_ID, "role": "assistant", "content": "Earlier.", "illustration": receipt}
    async with TestSessionLocal() as db:
        ids = restore_messages(db, SESSION_ID, [raw])
        await db.flush()
        message = await db.get(ChatMessage, ids[MESSAGE_ID])
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION_ID))
        status = illustration_status(state, message)
        assert status["image_url"] is None and status["generation_details"] is None
        assert message.illustration == receipt


async def test_copy_detaches_receipt_and_keeps_revision_and_content(illustrated_save):
    async with TestSessionLocal() as db:
        original = await db.get(ChatMessage, MESSAGE_ID)
        receipt = deepcopy(original.illustration)
        ids = await copy_messages(db, SESSION_ID, "other-session")
        copied = next(row for row in db.new if isinstance(row, ChatMessage))
        assert copied.id == ids[original.id] != original.id
        assert copied.session_id == "other-session"
        assert copied.revision_id == original.revision_id
        assert copied.content == original.content
        assert content_hash(copied) == content_hash(original)
        assert copied.illustration == receipt
        copied.illustration["generation_details"]["queries"][0]["response"] = "Changed"
        assert original.illustration == receipt


@pytest.mark.parametrize("direction", ["export", "import"])
def test_asset_conversion_preserves_generation_details(direction, generation_details):
    receipt = {"image_url": IMAGE_URL, "generation_details": generation_details}
    if direction == "export":
        converted = localize_session_paths(receipt, SESSION_ID)
        expected_url = "assets/visuals/illustrations/moment.png"
    else:
        receipt["image_url"] = "assets/visuals/illustrations/moment.png"
        converted = restore_session_paths(receipt, "restored")
        expected_url = "/data/adventures/sessions/restored/visuals/illustrations/moment.png"
    assert converted["image_url"] == expected_url
    assert converted["generation_details"] == generation_details


async def assert_saved_receipt(client, session_id, generation_details, *, snapshot_available):
    message, state = await saved_rows(session_id)
    response = await client.get(
        f"/api/adventures/{session_id}/illustrations", params={"message_id": message.id}
    )
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["generation_details"] == generation_details
    assert status["image_url"] == message.illustration["image_url"]
    assert status["available"] is snapshot_available
    assert message.illustration["content_hash"] == content_hash(message)
    assert status["image_url"].startswith(f"/data/adventures/sessions/{session_id}/")
    assert await asyncio.to_thread(Path(data_url_to_local_path(status["image_url"])).is_file)
    assert CACHE_KEY not in state.entity_states
    registry = registry_of(state.entity_states)
    if snapshot_available:
        assert set(registry["snapshots"]) == {message.id}
        assert registry["snapshots"][message.id]["source_message_id"] == message.id
        assert registry["snapshots"][message.id]["source_revision_id"] == message.revision_id
        assert registry["images"][message.id]["image_url"] == status["image_url"]
    else:
        assert registry["snapshots"] == registry["images"] == {}
    return message, state


async def export_and_import(client, session_id, generation_details):
    exported = await client.get(f"/api/adventures/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
        receipt = manifest["chat_messages"][0]["illustration"]
        assert receipt["generation_details"] == generation_details
        assert receipt["image_url"].startswith("assets/")
        assert archive.read(receipt["image_url"])
    imported = await client.post(
        "/api/adventures/sessions/import",
        files={"file": ("save.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    return imported.json()["game_id"]


@pytest.mark.parametrize("evicted", [False, True])
async def test_copy_and_two_archive_roundtrips_preserve_details_and_query(
    auth_client, illustrated_save, generation_details, evicted
):
    if evicted:
        async with TestSessionLocal() as db:
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == SESSION_ID)
            )
            state.entity_states = {
                **state.entity_states,
                REGISTRY_KEY: {"snapshots": {}, "images": {}},
            }
            await db.commit()
    original, original_state = await saved_rows(SESSION_ID)
    copied = await auth_client.post(f"/api/adventures/sessions/{SESSION_ID}/copy")
    assert copied.status_code == 201, copied.text
    session_id = copied.json()["game_id"]
    ids = {original.id}
    previous_snapshot = registry_of(original_state.entity_states)["snapshots"].get(original.id)
    for _ in range(3):
        message, state = await assert_saved_receipt(
            auth_client, session_id, generation_details, snapshot_available=not evicted
        )
        assert message.id not in ids
        ids.add(message.id)
        assert message.revision_id == original.revision_id
        assert content_hash(message) == content_hash(original)
        snapshot = registry_of(state.entity_states)["snapshots"].get(message.id)
        if previous_snapshot:
            assert snapshot["nonce"] != previous_snapshot["nonce"]
        previous_snapshot = snapshot
        copied_bytes = await asyncio.to_thread(
            Path(data_url_to_local_path(message.illustration["image_url"])).read_bytes
        )
        original_bytes = await asyncio.to_thread(
            Path(data_url_to_local_path(original.illustration["image_url"])).read_bytes
        )
        assert copied_bytes == original_bytes
        if len(ids) < 4:
            session_id = await export_and_import(auth_client, session_id, generation_details)
    unchanged, unchanged_state = await saved_rows(SESSION_ID)
    assert unchanged.illustration == original.illustration
    assert unchanged_state.entity_states == original_state.entity_states


async def test_legacy_bundle_restores_illustration(auth_client, bundle, generation_details):
    receipt = {
        "image_url": "https://example.org/moment.png",
        "generation_details": generation_details,
    }
    bundle["chat_history"][0]["illustration"] = receipt
    response = await auth_client.post("/api/adventures/import/session-bundle", json=bundle)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        game = await db.scalar(
            select(GameSession).where(GameSession.template_id == response.json()["adventure_id"])
        )
        message = await db.scalar(select(ChatMessage).where(ChatMessage.session_id == game.id))
        assert message.id != "old-message"
        assert message.illustration == receipt


async def test_full_history_backup_restores_receipt(illustrated_save, generation_details):
    async with TestSessionLocal() as db:
        snapshot = await capture(db, SESSION_ID, backup=True)
        message = await db.get(ChatMessage, MESSAGE_ID)
        receipt = deepcopy(message.illustration)
        message.illustration = None
        await db.flush()
        await restore(db, SESSION_ID, snapshot)
        restored = await db.get(ChatMessage, MESSAGE_ID, populate_existing=True)
        assert restored.illustration == receipt
        assert restored.illustration["generation_details"] == generation_details
