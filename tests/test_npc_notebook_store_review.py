"""Controlled independent SQLite writers preserve first-insert CAS and session quota."""

import asyncio
from contextlib import suppress

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.engine.chpm import notebook_store
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.models.npc_notebook import NpcNotebook
from backend.models.world_entity import WorldEntity
from tests.test_chpm_host_state import mind
from tests.test_session_progress_portability import progress_db

__all__ = ["progress_db"]


async def _actors(db):
    db.add_all(
        [
            WorldEntity(
                session_id="source",
                id=actor,
                entity_type="NPC",
                name=actor,
                description="A fictional resident.",
                current_scene_id="ROOM",
            )
            for actor in ("LILI", "MIRINDA")
        ]
    )
    await db.commit()


def _lookup(statement, result, *, capacity):
    if capacity:
        return result == 0 and "count(" in str(statement).lower()
    description = getattr(statement, "column_descriptions", [{}])[0]
    return result is None and description.get("entity") is NpcNotebook


async def _race(db, monkeypatch, *, capacity):
    await _actors(db)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    first_read, second_read, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def writer(first):
        async with factory() as connection:
            original = connection.scalar

            async def scalar(statement, *args, **kwargs):
                result = await original(statement, *args, **kwargs)
                if not _lookup(statement, result, capacity=capacity):
                    return result
                if first:
                    first_read.set()
                    # A correct reservation blocks the second lookup until commit.
                    with suppress(TimeoutError):
                        await asyncio.wait_for(second_read.wait(), 0.2)
                else:
                    second_read.set()
                    await committed.wait()
                return result

            monkeypatch.setattr(connection, "scalar", scalar)
            actor = "MIRINDA" if capacity and not first else "LILI"
            workspace = NotebookWorkspace()
            workspace.write("/note", '"first"' if first else '"second"', expected_revision=0)
            try:
                await notebook_store.persist_workspace(
                    connection, mind(actor, "source"), workspace, owner_id="owner"
                )
                await connection.commit()
                return None, connection.is_active
            except Exception as exc:
                return exc, connection.is_active
            finally:
                if first:
                    committed.set()

    first = asyncio.create_task(writer(True))
    await asyncio.wait_for(first_read.wait(), 5)
    second = asyncio.create_task(writer(False))
    return await asyncio.wait_for(asyncio.gather(first, second), 5)


@pytest.mark.parametrize("progress_db", ["file"], indirect=True)
async def test_concurrent_empty_insert_loser_is_cas_conflict_without_poisoning_outer_transaction(
    progress_db, monkeypatch
):
    results = await _race(progress_db, monkeypatch, capacity=False)
    assert results[0] == (None, True)
    error, active = results[1]
    assert isinstance(error, ChpmError), (
        f"Expected a recoverable CAS conflict, got {type(error).__name__}"
    )
    assert active, "A notebook conflict must not invalidate the caller's transaction."
    rows = list(await progress_db.scalars(select(NpcNotebook)))
    assert len(rows) == 1 and rows[0].payload == b'{"note":"first"}'


@pytest.mark.parametrize("progress_db", ["file"], indirect=True)
async def test_concurrent_new_npcs_cannot_both_consume_last_session_slot(progress_db, monkeypatch):
    monkeypatch.setattr(notebook_store, "MAX_NOTEBOOKS", 1)
    results = await _race(progress_db, monkeypatch, capacity=True)
    assert results[0] == (None, True)
    error, active = results[1]
    assert isinstance(error, ChpmError), "Only one independent writer can consume the final slot."
    assert active
    assert await progress_db.scalar(select(func.count()).select_from(NpcNotebook)) == 1
