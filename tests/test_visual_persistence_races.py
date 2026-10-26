"""Persist generated visuals without overwriting concurrent story or NPC data."""

import sqlite3
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from backend.engine import session_portraits
from backend.engine.memory_rag import persistence
from backend.engine.npc_journal import portraits
from backend.engine.npc_journal.records import JOURNAL_KEY
from backend.engine.scene_illustrations import generation
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_scene_illustrations import finish, illustration_world
from tests.test_session_portraits import finish_job, portrait_world, start_job

__all__ = ["portrait_world", "illustration_world"]


async def test_portrait_cas_preserves_edit_between_read_and_write(portrait_world, monkeypatch):
    original = session_portraits._context
    calls = 0

    async def context(db, *args):
        nonlocal calls
        state, npc = await original(db, *args)
        calls += 1
        if calls == 1:
            async with TestSessionLocal() as other:
                current = await other.scalar(
                    select(SessionState).where(SessionState.id == state.id)
                )
                values = deepcopy(current.entity_states)
                values["NPC_NEW"]["hp"] = 5
                values["new_fact"] = "Committed after portrait read"
                current.entity_states = values
                await other.commit()
        return state, npc

    monkeypatch.setattr(session_portraits, "_context", context)
    async with TestSessionLocal() as db:
        owner = (await db.scalars(select(User))).first().id
    await session_portraits._save_portrait("portrait-session", "NPC_NEW", owner, "/data/new.png")
    assert calls == 2
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states["NPC_NEW"]["image_url"] == "/data/new.png"
        assert state.entity_states["NPC_NEW"]["hp"] == 5
        assert state.entity_states["new_fact"] == "Committed after portrait read"


async def test_portrait_status_cas_preserves_new_journal_fact(portrait_world, monkeypatch):
    original = AsyncSession.execute
    raced = False

    async def execute(db, statement, *args, **kwargs):
        nonlocal raced
        if isinstance(statement, Update) and statement.table.name == "world_entities" and not raced:
            raced = True
            async with TestSessionLocal() as other:
                npc = await other.scalar(
                    select(WorldEntity).where(
                        WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
                    )
                )
                npc.metadata_json = {**(npc.metadata_json or {}), "new_fact": "Keep me"}
                await other.commit()
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute)
    assert not await portraits._mark("portrait-session", "NPC_NEW", "running")
    assert raced
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        assert npc.metadata_json["new_fact"] == "Keep me"
        assert npc.metadata_json[JOURNAL_KEY]["portrait_status"] == "ready"


async def test_portrait_busy_save_does_not_repeat_generation(
    auth_client, portrait_world, monkeypatch
):
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = session_portraits._context
    calls = 0
    save_sessions = []

    async def context(db, *args):
        nonlocal calls
        calls += 1
        if calls > 1:
            save_sessions.append(db)
        value = await original(db, *args)
        if calls == 2:
            raise sqlite3.OperationalError("database is locked")
        return value

    monkeypatch.setattr(session_portraits, "_context", context)
    body = await start_job(auth_client)
    result = await finish_job(auth_client, body)
    assert result["state"] == "succeeded", result
    assert len(portrait_world) == 1
    assert len(save_sessions) == 2 and save_sessions[0] is not save_sessions[1]


async def test_illustration_busy_attach_does_not_repeat_generation(
    auth_client, illustration_world, monkeypatch
):
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = generation._try_attach
    sessions = []

    async def attach(db, *args):
        sessions.append(db)
        if len(sessions) == 1:
            raise sqlite3.OperationalError("database is locked")
        return await original(db, *args)

    monkeypatch.setattr(generation, "_try_attach", attach)
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert len(illustration_world) == 1
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
