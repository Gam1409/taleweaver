"""Cross-module lifecycle actions preserve one current private notebook per NPC."""

import hashlib
import io
import json
import zipfile
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from backend.api.routes.adventures import legacy_session_mutations
from backend.api.routes.adventures.sessions import copy_session
from backend.api.routes.adventures.template_reset import rebuild_template_world
from backend.engine import adventure_updates
from backend.engine.chpm.notebook import MAX_BYTES, NotebookWorkspace, encode
from backend.engine.chpm.notebook_store import load_snapshot, persist_workspace
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture
from backend.engine.turn_replay.undo import undo_latest
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.npc_notebook import NpcNotebook
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, update
from tests.test_chpm_host_state import mind
from tests.test_narration_regeneration import narration
from tests.test_npc_notebook_lifecycle import _npc, _write
from tests.test_session_portraits import portrait_world
from tests.test_session_progress_portability import progress_db

__all__ = ["chpm_world", "narration", "portrait_world", "progress_db"]
CANARY = "PRIVATE_NOTEBOOK_COMPATIBILITY_SENTINEL"


async def _portrait_note(db, value):
    game = await db.get(GameSession, "portrait-session")
    actor = mind("NPC_NEW", game.id)
    original = await load_snapshot(db, actor, game.user_id)
    workspace = NotebookWorkspace(original.payload, revision=original.revision)
    workspace.write("", encode(value).decode(), expected_revision=original.revision)
    await persist_workspace(db, actor, workspace, owner_id=game.user_id)
    await db.commit()
    row = await db.scalar(select(NpcNotebook))
    return row.id, row.sha256, row.byte_size, row.revision


async def _identity(db, session_id):
    row = await db.scalar(select(NpcNotebook).where(NpcNotebook.session_id == session_id))
    assert row.sha256 == hashlib.sha256(row.payload).hexdigest()
    return row.id, row.sha256, row.byte_size, row.revision


async def test_regeneration_and_narration_revision_restore_keep_exact_limit_notebook(
    auth_client, narration
):
    message_id, llm = narration
    value = CANARY + "x" * (MAX_BYTES - 2 - len(CANARY))
    async with TestSessionLocal() as db:
        before = await _portrait_note(db, value)
        assert before[2] == MAX_BYTES
    response = await auth_client.post(
        "/api/adventures/portrait-session/chat/regenerate", json={"message_id": message_id}
    )
    assert response.status_code == 200, response.text
    assert CANARY not in str(llm.aexecute_simple_task.await_args)
    versions_path = f"/api/adventures/portrait-session/chat/{message_id}/versions"
    versions = await auth_client.get(versions_path)
    assert versions.status_code == 200
    assert CANARY not in versions.text
    original = versions.json()["versions"][0]
    restored = await auth_client.post(
        versions_path + "/restore",
        json={
            "version_id": original["id"],
            "expected_revision_id": response.json()["revision_id"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["content"] == "The gate remains locked."
    async with TestSessionLocal() as db:
        assert await _identity(db, "portrait-session") == before
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1


async def test_actual_mode_and_notebook_settings_api_keeps_the_current_document(
    auth_client, chpm_world
):
    async with TestSessionLocal() as db:
        before = await _portrait_note(db, {"note": CANARY})
    for revision, (mode, enabled) in enumerate(
        (("live", True), ("off", False), ("shadow", True), ("live", True))
    ):
        response = await auth_client.patch(
            "/api/adventures/portrait-session/chpm",
            json=update(
                mode,
                revision=revision,
                notebook_enabled=enabled,
                agent_steps=1,
                max_calls_per_turn=25,
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["settings"]["notebook_enabled"] is enabled
        assert CANARY not in response.text
        async with TestSessionLocal() as db:
            assert await _identity(db, "portrait-session") == before


async def test_actual_undo_entrypoint_keeps_latest_notebook_without_a_snapshot_copy(progress_db):
    db = progress_db
    await _write(db, "NPC", {"note": "before"})
    await db.commit()
    before = await capture(db, "source")
    assert "npc_notebooks" not in before["tables"]
    db.add(ChatMessage(session_id="source", role="user", content="Inspect the bridge."))
    reply = ChatMessage(session_id="source", role="assistant", content="The bridge is sound.")
    db.add(reply)
    await db.flush()
    reply_id = reply.id
    db.add(
        TurnReplay(
            session_id="source",
            before=before,
            input_text="Inspect the bridge.",
            assistant_id=reply_id,
            status="ready",
        )
    )
    await _write(db, "NPC", {"note": "latest"})
    await db.commit()
    identity = await _identity(db, "source")
    count = await undo_latest(db, await db.get(GameSession, "source"), reply_id)
    await db.commit()
    assert count == 2
    assert await db.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await db.get(TurnReplay, "source") is None
    assert await _identity(db, "source") == identity
    assert (await load_snapshot(db, mind("NPC", "source"), "owner")).payload == b'{"note":"latest"}'


async def test_legacy_ads_and_session_copy_leave_notebooks_absent_until_first_write(progress_db):
    db = progress_db
    await _npc(db, "NPC")
    await db.commit()
    payload = await SessionExporter.export_ads(db, "source")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert "npc_notebooks" not in json.loads(archive.read("session.json"))
        assert not any(name.startswith("npc-notebooks/") for name in archive.namelist())
    imported_id = await SessionImporter.import_ads(db, payload, "owner")
    copied = await copy_session("source", db, await db.get(User, "owner"))
    assert imported_id
    for session_id in ("source", imported_id, copied["game_id"]):
        assert (await load_snapshot(db, mind("NPC", session_id), "owner")).payload == b"{}"
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0


async def test_template_patch_rebuild_delete_and_detached_ads_keep_session_notebook(
    auth_client, portrait_world, monkeypatch
):
    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.cleanup_adventure_assets", AsyncMock()
    )
    async with TestSessionLocal() as db:
        before = await _portrait_note(db, {"note": CANARY})
        template = await db.get(AdventureTemplate, "portrait-template")
        template.original_manifest = {
            "scenes": [{"id": "TOWER", "name": "Tower"}],
            "npcs": [{"id": "TEMPLATE_ONLY", "name": "Architect", "start_scene_id": "TOWER"}],
        }
        await db.commit()
    patched = await auth_client.patch(
        "/api/adventures/portrait-template", json={"plot": "A revised authored plot."}
    )
    assert patched.status_code == 200, patched.text
    async with TestSessionLocal() as db:
        await rebuild_template_world(db, await db.get(AdventureTemplate, "portrait-template"))
        await db.commit()
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.plot == "A revised authored plot."
        assert await _identity(db, "portrait-session") == before
    deleted = await auth_client.delete("/api/adventures/portrait-template")
    assert deleted.status_code == 200, deleted.text
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, "portrait-session")
        owner = game.user_id
        assert game.template_id is None
        assert await _identity(db, game.id) == before
        assert (await load_snapshot(db, mind("NPC_NEW", game.id), owner)).payload == encode(
            {"note": CANARY}
        )
        imported_id = await SessionImporter.import_ads(
            db, await SessionExporter.export_ads(db, game.id), owner
        )
        assert imported_id
        imported = await load_snapshot(db, mind("NPC_NEW", imported_id), owner)
        assert imported.payload == encode({"note": CANARY})


async def test_disk_template_replacement_relinks_but_does_not_replace_personal_notebook(
    progress_db, monkeypatch, tmp_path
):
    db = progress_db
    await _write(db, "NPC", {"note": CANARY})
    await db.commit()
    before = await _identity(db, "source")
    path = tmp_path / "updated.adv"
    path.write_text(
        json.dumps(
            {
                "format": "TaleWeaver",
                "version": "1.3",
                "title": "Progress story",
                "image_url": "/data/authored-cover.png",
                "plot": "Replacement authored plot.",
                "scenes": [{"id": "NEW_ROOM", "name": "New room", "description": "A room."}],
                "npcs": [
                    {
                        "id": "NPC",
                        "name": "New author identity",
                        "description": "Authored replacement.",
                        "start_scene_id": "NEW_ROOM",
                        "image_url": "/data/authored-npc.png",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(
        adventure_updates,
        "scan_available_adventure_files",
        lambda **_: [{"title": "Progress story", "file_path": str(path), "version": "1.3"}],
    )
    for name in ("cleanup_adventure_assets", "ensure_thumbnails"):
        monkeypatch.setattr("backend.engine.media_engine.MediaEngine." + name, AsyncMock())
    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.generate_placeholder",
        AsyncMock(return_value="/data/placeholder.png"),
    )
    result = await adventure_updates.update_single_adventure(db, "template", "owner")
    assert result["status"] == "success"
    game = await db.get(GameSession, "source", populate_existing=True)
    assert game.template_id == result["template_id"] and game.template_id != "template"
    actor = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == "source", WorldEntity.id == "NPC")
    )
    assert actor.current_scene_id == "ROOM" and actor.description == "An engineer."
    assert await _identity(db, "source") == before


async def test_legacy_bulk_reset_cascades_current_notebooks_with_session_deletion(
    progress_db, monkeypatch
):
    db = progress_db
    await _write(db, "NPC", {"note": CANARY})
    await db.commit()
    monkeypatch.setattr(legacy_session_mutations, "purge_session_memory", AsyncMock())
    await legacy_session_mutations.reset_sessions(db, "template", "owner")
    assert await db.scalar(select(func.count()).select_from(GameSession)) == 0
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0
    assert await db.get(AdventureTemplate, "template") is not None
