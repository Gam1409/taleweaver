"""Current personal notebooks survive portability while world rewinds leave them alone."""

import hashlib
import io
import json
import zipfile

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures.sessions import copy_session
from backend.engine.chpm import notebook_store
from backend.engine.chpm.notebook import NotebookWorkspace, encode
from backend.engine.chpm.notebook_store import load_snapshot, persist_workspace
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.game_session import GameSession
from backend.models.npc_notebook import NpcNotebook
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.test_chpm_host_state import mind
from tests.test_session_progress_portability import progress_db

__all__ = ["progress_db"]


async def _write(db, actor, value, session_id="source"):
    await _npc(db, actor, session_id)
    actor_mind = mind(actor, session_id)
    before = await load_snapshot(db, actor_mind, "owner")
    workspace = NotebookWorkspace(before.payload, before.revision)
    workspace.write("", encode(value).decode(), expected_revision=before.revision)
    await persist_workspace(db, actor_mind, workspace, owner_id="owner")


async def _npc(db, actor, session_id="source"):
    existing = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == session_id, WorldEntity.id == actor)
    )
    if existing is None:
        db.add(
            WorldEntity(
                id=actor,
                session_id=session_id,
                entity_type="NPC",
                name=actor,
                description="An engineer.",
                current_scene_id="ROOM",
            )
        )
        await db.flush()


async def _state(db, session_id="source"):
    return await db.scalar(select(SessionState).where(SessionState.session_id == session_id))


async def _hashes(db, session_id):
    records = await db.scalars(
        select(NpcNotebook).where(NpcNotebook.session_id == session_id).order_by(NpcNotebook.npc_id)
    )
    return {row.npc_id: hashlib.sha256(row.payload).hexdigest() for row in records}


async def test_one_current_row_is_not_copied_into_checkpoints_or_turn_replay(progress_db):
    db = progress_db
    await _write(db, "NPC", {"note": "before"})
    await db.commit()
    original_id = await db.scalar(select(NpcNotebook.id))
    checkpoint = await SessionCheckpointService.create_checkpoint(db, "source", "MANUAL")
    snapshot = await capture(db, "source")
    assert "npc_notebooks" not in snapshot["tables"]
    assert "notebook" not in json.dumps(checkpoint.state_snapshot)
    await _write(db, "NPC", {"note": "latest"})
    await db.commit()
    await SessionCheckpointService.restore_checkpoint(db, "source", checkpoint.id)
    await db.commit()
    await restore(db, "source", snapshot)
    await db.commit()
    notebook = await load_snapshot(db, mind("NPC", "source"), "owner")
    assert notebook.payload == b'{"note":"latest"}'
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1
    assert await db.scalar(select(NpcNotebook.id)) == original_id


async def test_same_session_export_refreshes_a_strongly_held_notebook_row(progress_db):
    db = progress_db
    await _write(db, "NPC", {"note": "before"})
    await db.commit()
    held = await db.scalar(select(NpcNotebook))
    assert held is not None
    await _write(db, "NPC", {"note": "latest"})
    await db.commit()
    exported = await SessionExporter.export_ads(db, "source")
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        manifest = json.loads(archive.read("session.json"))
        part = manifest["npc_notebooks"]["parts"][0]
        assert json.loads(archive.read(part["path"]))[0]["document"] == {"note": "latest"}


async def test_four_near_full_documents_copy_export_import_without_text_rewriting(progress_db):
    db = progress_db
    for index in range(4):
        await _write(
            db,
            f"NPC{index}",
            {
                "assets": "assets/private.json",
                "note": "x" * 15_999_850,
                "session_path": "/data/adventures/sessions/source/private.json",
            },
        )
    await db.commit()
    original = await _hashes(db, "source")
    copied = await copy_session("source", db, await db.get(User, "owner"))
    copied_id = copied["game_id"]
    assert await _hashes(db, copied_id) == original
    output = io.BytesIO()
    await SessionExporter.export_ads_to(db, "source", output)
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("session.json"))
        assert archive.getinfo("session.json").file_size < 1024 * 1024
        assert manifest["npc_notebooks"]["rows"] == 4
        assert len([name for name in archive.namelist() if name.startswith("npc-notebooks/")]) == 4
    output.seek(0)
    imported_id = await SessionImporter.import_ads_from(db, output, "owner")
    assert imported_id
    assert await _hashes(db, imported_id) == original
    await _write(db, "NPC0", {"note": "independent"}, copied_id)
    await db.commit()
    assert await _hashes(db, "source") == original
    assert await _hashes(db, imported_id) == original
    assert (await _hashes(db, copied_id))["NPC0"] != original["NPC0"]


async def test_default_and_imported_notebooks_are_independent_of_personality_modes(progress_db):
    db = progress_db
    await _npc(db, "NPC")
    assert (await load_snapshot(db, mind("NPC", "source"), "owner")).payload == b"{}"
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0
    await _write(db, "NPC", {"private": ["a", "b"]})
    await db.commit()
    state = await _state(db)
    for mode in ("off", "shadow", "live", "off"):
        state.entity_states = {
            **state.entity_states,
            "__chpm__": {"schema_version": 6, "settings": {"mode": mode, "actor_ids": ["NPC"]}},
        }
        await db.commit()
        assert (
            await load_snapshot(db, mind("NPC", "source"), "owner")
        ).payload == b'{"private":["a","b"]}'


async def test_session_delete_cascades_only_its_current_notebooks(progress_db):
    from backend.core.relational_delete import delete_owned_rows

    db = progress_db
    await _write(db, "NPC", {"private": "kept"})
    await db.commit()
    copied = await copy_session("source", db, await db.get(User, "owner"))
    await delete_owned_rows(db, GameSession.__table__, GameSession.id == copied["game_id"])
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1
    assert (
        await load_snapshot(db, mind("NPC", "source"), "owner")
    ).payload == b'{"private":"kept"}'


async def test_session_notebook_count_capacity_preserves_prior_documents(progress_db, monkeypatch):
    db = progress_db
    monkeypatch.setattr(notebook_store, "MAX_NOTEBOOKS", 1)
    await _write(db, "NPC", {"note": "kept"})
    await db.commit()
    with pytest.raises(ValueError, match="capacity"):
        await _write(db, "OTHER", {"note": "rejected"})
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1
    assert (await load_snapshot(db, mind("NPC", "source"), "owner")).payload == b'{"note":"kept"}'


async def test_untrusted_notebook_npc_rejects_the_whole_ads_import(progress_db):
    db = progress_db
    await _write(db, "NPC", {"note": "kept"})
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(GameSession))
    exported = await SessionExporter.export_ads(db, "source")
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported)) as source:
        manifest = json.loads(source.read("session.json"))
        part = manifest["npc_notebooks"]["parts"][0]
        rows = json.loads(source.read(part["path"]))
        rows[0]["npc_id"] = "UNKNOWN_NPC"
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
        part.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        with zipfile.ZipFile(changed, "w", compression=zipfile.ZIP_STORED) as target:
            for name in source.namelist():
                value = payload if name == part["path"] else source.read(name)
                if name == "session.json":
                    value = json.dumps(manifest).encode()
                target.writestr(name, value)
    assert await SessionImporter.import_ads(db, changed.getvalue(), "owner") is None
    assert await db.scalar(select(func.count()).select_from(GameSession)) == before
    assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1
    assert (await load_snapshot(db, mind("NPC", "source"), "owner")).payload == b'{"note":"kept"}'


async def test_rewound_generated_npc_notes_remain_portable_but_dormant(progress_db):
    db = progress_db
    before = await capture(db, "source")
    await db.commit()
    await _write(db, "GENERATED", {"note": "latest retained note"})
    await db.commit()
    await restore(db, "source", before)
    await db.commit()
    assert not await notebook_store.npc_present(db, "source", "GENERATED")
    with pytest.raises(ValueError, match="NPC is unavailable"):
        await load_snapshot(db, mind("GENERATED", "source"), "owner")
    exported = await SessionExporter.export_ads(db, "source")
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        manifest = json.loads(archive.read("session.json"))
        part = manifest["npc_notebooks"]["parts"][0]
        assert json.loads(archive.read(part["path"]))[0]["dormant"] is True
    copied = await copy_session("source", db, await db.get(User, "owner"))
    imported_id = await SessionImporter.import_ads(db, exported, "owner")
    assert imported_id
    for target in (copied["game_id"], imported_id):
        assert not await notebook_store.npc_present(db, target, "GENERATED")
        with pytest.raises(ValueError, match="NPC is unavailable"):
            await load_snapshot(db, mind("GENERATED", target), "owner")
        workspace = NotebookWorkspace()
        workspace.write("/note", '"must remain blocked"', expected_revision=0)
        with pytest.raises(ValueError, match="NPC is unavailable"):
            await persist_workspace(db, mind("GENERATED", target), workspace, owner_id="owner")
        await _npc(db, "GENERATED", target)
        assert (
            await load_snapshot(db, mind("GENERATED", target), "owner")
        ).payload == b'{"note":"latest retained note"}'
