"""Index controls must not reuse generations or overwrite concurrently queued work."""

from sqlalchemy import select
from sqlalchemy.sql.dml import Insert

from backend.engine.memory_rag.control import ensure_index_states, invalidate
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


async def seed_index():
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        db.add(
            MemoryIndexState(
                session_id=session.id, user_id=session.user_id, template_id=session.template_id
            )
        )
        await db.commit()
        return session.user_id


async def test_two_stale_controls_get_distinct_epochs(portrait_world):
    await seed_index()
    async with TestSessionLocal() as older, TestSessionLocal() as newer:
        old_row = await older.get(MemoryIndexState, "portrait-session")
        new_row = await newer.get(MemoryIndexState, "portrait-session")
        await invalidate(newer, new_row, paused=True)
        await newer.commit()
        assert new_row.epoch == 1
        await invalidate(older, old_row, paused=True)
        await older.commit()
        assert old_row.epoch == 2
        assert old_row.desired_revision == 3


async def test_invalidation_keeps_new_dirty_revisions_and_current_pause(portrait_world):
    await seed_index()
    async with TestSessionLocal() as older, TestSessionLocal() as newer:
        old_row = await older.get(MemoryIndexState, "portrait-session")
        new_row = await newer.get(MemoryIndexState, "portrait-session")
        new_row.desired_revision = 12
        new_row.paused = True
        await newer.commit()
        await invalidate(older, old_row)
        await older.commit()
        assert old_row.desired_revision == 13
        assert old_row.paused is True
        assert old_row.status == "paused"


async def test_initialization_accepts_concurrent_insert_without_resetting_it(
    portrait_world, monkeypatch
):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        execute = db.execute
        raced = False

        async def race_insert(statement, *args, **kwargs):
            nonlocal raced
            if isinstance(statement, Insert) and not raced:
                raced = True
                async with TestSessionLocal() as other:
                    other.add(
                        MemoryIndexState(
                            session_id=session.id,
                            user_id=session.user_id,
                            template_id=session.template_id,
                            epoch=7,
                            desired_revision=19,
                            paused=True,
                            status="paused",
                        )
                    )
                    await other.commit()
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", race_insert)
        rows = await ensure_index_states(
            db, user_id=session.user_id, template_id=session.template_id
        )
        await db.commit()
        assert raced
        assert len(rows) == 1
        assert (rows[0].epoch, rows[0].desired_revision, rows[0].paused) == (7, 19, True)
        assert len(list(await db.scalars(select(MemoryIndexState)))) == 1
