"""Lossless storage, ownership and transport regression tests for the full review."""

import io
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from backend.core.llm_roles import resolve_llm_role
from backend.core.relational_delete import delete_owned_rows
from backend.engine.import_archive import _extract_archive_assets
from backend.engine.manifest_apply.validation import validate_world_references
from backend.engine.media_file_operations import persist_image_bytes
from backend.engine.npc_journal.archive import compact, expanded
from backend.engine.npc_journal.lifecycle import remap_journal
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.retraction import retract_reply
from backend.models.game_session import GameSession
from backend.models.turn_replay import TurnReplay
from backend.utils import media_access
from tests.conftest import TestSessionLocal
from tests.test_living_world import seed


def journal(count=600):
    return {
        "entries": [{"id": str(i), "message_id": str(i), "text": f"Fact {i}"} for i in range(count)]
    }


def test_journal_archive_preserves_every_entry_and_bounds_working_copy():
    source = journal()
    stored = compact(source)
    assert len(stored["entries"]) <= 256
    assert expanded(stored)["entries"] == source["entries"]
    npc = SimpleNamespace(metadata_json={"npc_journal": stored})
    projection = journal_of(npc)
    projection["entries"].clear()
    assert len(journal_of(npc, full=True)["entries"]) == 600


def test_journal_archived_provenance_is_remapped_and_retracted():
    metadata = remap_journal({"npc_journal": compact(journal())}, {"1": "new-1"})
    npc = SimpleNamespace(metadata_json=metadata)
    assert journal_of(npc, full=True)["entries"][1]["message_id"] == "new-1"
    retract_reply(npc, "new-1")
    assert len(journal_of(npc, full=True)["entries"]) == 599
    assert not any(e["message_id"] == "new-1" for e in journal_of(npc, full=True)["entries"])


def test_archive_preserves_distinct_assets_with_same_basename(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.config.settings.DATA_DIR", str(tmp_path))
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("assets/a/image.png", b"first")
        archive.writestr("assets/b/image.png", b"second")
    with ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        mapping = _extract_archive_assets(archive, "new-world")
    assert mapping["assets/a/image.png"] != mapping["assets/b/image.png"]
    assert (tmp_path / "adventures/library/new-world/a/image.png").read_bytes() == b"first"


@pytest.mark.parametrize(
    "manifest",
    [
        {"scenes": [{"id": "A"}], "exits": [{"from_scene_id": "A", "to_scene_id": "MISSING"}]},
        {"scenes": [{"id": "A"}], "npcs": [{"id": "N", "name": "N", "start_scene_id": "MISSING"}]},
    ],
)
def test_manifest_references_rejected_before_persistence(manifest):
    with pytest.raises(ValueError, match="does not exist"):
        validate_world_references(manifest)


def test_provider_requires_its_own_model():
    with pytest.raises(ValueError, match="anthropic"):
        resolve_llm_role({"small_model_provider": "anthropic"}, "small")
    assert resolve_llm_role({}, "small").model == "gpt-4o-mini"


def test_non_jpeg_images_are_verified_before_persistence(tmp_path):
    output = tmp_path / "image.png"
    with pytest.raises(UnidentifiedImageError):
        persist_image_bytes(str(output), b"not an image", "png", 85)
    assert not output.exists()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    persist_image_bytes(str(output), buffer.getvalue(), "png", 85)
    with Image.open(output) as image:
        assert image.size == (8, 8)


async def test_deleting_session_removes_replay_without_orm_relationship(setup_test_db):
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        db.add(
            TurnReplay(session_id=state.session_id, before={}, input_text="hello", status="pending")
        )
        await db.commit()
        await delete_owned_rows(
            db, GameSession.__table__, GameSession.__table__.c.id == state.session_id
        )
        await db.commit()
        assert await db.scalar(select(TurnReplay.session_id)) is None


async def test_media_cookie_is_read_only_and_owner_scoped(setup_test_db, monkeypatch):
    monkeypatch.setattr(media_access, "AsyncSessionLocal", TestSessionLocal)
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        response = Response()
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/auth/me",
                "scheme": "https",
                "headers": [],
                "server": ("test", 443),
                "query_string": b"",
            }
        )
        media_access.issue_media_cookie(response, request, user)
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        scope = {"type": "http", "headers": [(b"cookie", cookie.encode())]}
        await media_access.authorize_media(f"adventures/sessions/{state.session_id}/x.png", scope)
        user.role = "user"
        await db.commit()
        with pytest.raises(HTTPException) as denied:
            await media_access.authorize_media("adventures/sessions/foreign/x.png", scope)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as anonymous:
            await media_access.authorize_media("image.png", {"type": "http", "headers": []})
        assert anonymous.value.status_code == 401


def test_legacy_orphan_migration_keeps_recoverable_payload():
    import importlib.util
    import json

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "review_repair_migration",
        "alembic/versions/9ad17e20c001_preserve_orphans_before_fk_enforcement.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id), value TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO child VALUES ('orphan', 'missing', 'preserve this')"
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        payload = connection.exec_driver_sql(
            "SELECT payload FROM referential_repair_archive"
        ).scalar_one()
        assert json.loads(payload)["value"] == "preserve this"
        module.upgrade()
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM referential_repair_archive"
            ).scalar_one()
            == 1
        )
    engine.dispose()


async def test_command_recovery_restores_intermediate_commits(setup_test_db):
    from backend.engine.turn_replay.commands import prepare_command
    from backend.engine.turn_replay.service import recover
    from backend.models.avatar import Avatar

    async with TestSessionLocal() as db:
        user, state = await seed(db)
        session = await db.get(GameSession, state.session_id)
        avatar = await db.get(Avatar, session.avatar_id)
        original_hp = avatar.hp
        manager = SimpleNamespace(db=db, game_id=state.session_id, avatar=avatar)
        await prepare_command(manager, "/rest")
        avatar.hp = 1
        await db.commit()
        assert await recover(db, state.session_id)
        await db.refresh(avatar)
        assert avatar.hp == original_hp


async def test_non_admin_cannot_bypass_test_permissions_through_visual_jobs():
    from uuid import uuid4

    from backend.api.routes.visual_jobs import VisualJobRequest, create_visual_job

    payload = VisualJobRequest(id=str(uuid4()), operation="test", payload={"provider": "openai"})
    with pytest.raises(HTTPException) as denied:
        await create_visual_job(payload, SimpleNamespace(role="user", id="ordinary"))
    assert denied.value.status_code == 403
