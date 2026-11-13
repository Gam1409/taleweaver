"""Copied/imported passage rules drive actual movement and stored transition hooks."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.session_copy_world import clone_saved_world
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.models import Avatar, SessionState, WorldExit
from tests.conftest import TestSessionLocal
from tests.traversal_exit_support import add_session, seed_traversal_world, traverse

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("operation", ["copy", "import"])
async def test_passage_keeps_current_lock_and_hooks_after_world_lifecycle(
    tmp_path, monkeypatch, operation
):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db)
        if operation == "copy":
            session, state, avatar = await add_session(db, "copied", world.template, world.user)
            await clone_saved_world(db, world.sessions["one"], session, {}, {})
            await db.commit()
            session_id = session.id
        else:
            archive = await SessionExporter.export_ads(db, "one")
            session_id = await SessionImporter.import_ads(db, archive, world.user.id)
            assert session_id is not None
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == session_id)
            )
            avatar = await db.get(Avatar, state.avatar_id)
        world.states[session_id] = state
        world.avatars[session_id] = avatar
        row = await db.scalar(select(WorldExit).where(WorldExit.session_id == session_id))
        assert row.id != world.exits["one"].id
        assert row.is_locked is False
        assert row.unlock_expression == world.exits["one"].unlock_expression
        chunks = await traverse(world, session_id, "START::END", monkeypatch)
        assert any("event: scene_transition" in chunk for chunk in chunks)
        assert state.current_scene_id == "END"
        assert state.entity_states["__script_vars__"]["passage_source"] == "one"
        async with TestSessionLocal() as reader:
            saved = await reader.scalar(
                select(SessionState).where(SessionState.session_id == session_id)
            )
            assert saved.current_scene_id == "END"
            assert saved.entity_states["__script_vars__"]["passage_source"] == "one"
