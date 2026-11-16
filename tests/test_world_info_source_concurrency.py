"""File-SQLite transactions serialize quotas without changing gameplay metadata."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.engine.world_info import limits, sources
from backend.engine.world_info.access import WorldInfoError
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoSource


@pytest_asyncio.fixture
async def file_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'source-quota.sqlite'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with maker() as db:
        db.add(
            User(id="quota-owner", username="quota-owner", hashed_password="fictional-test-hash")
        )
        db.add(Avatar(id="quota-avatar", user_id="quota-owner", name="Hero"))
        await db.flush()
        db.add(GameSession(id="quota-session", user_id="quota-owner", avatar_id="quota-avatar"))
        await db.commit()
    yield maker
    await engine.dispose()


@pytest.mark.parametrize("quota", ["source_count", "source_bytes"])
async def test_concurrent_uploads_recheck_quota_inside_the_first_writer(
    file_database, monkeypatch, quota
):
    if quota == "source_count":
        monkeypatch.setattr(limits, "MAX_SOURCES", 1)
    else:
        monkeypatch.setattr(limits, "MAX_SESSION_SOURCE_BYTES", 25)
    original = sources._capacity
    both_read = asyncio.Event()
    arrivals = 0

    async def capacity(*args):
        nonlocal arrivals
        count = await original(*args)
        arrivals += 1
        if arrivals == 2:
            both_read.set()
        # Without an initial write both stale reads rendezvous. With the writer
        # gate, the second upload correctly waits until this transaction commits.
        try:
            await asyncio.wait_for(both_read.wait(), 0.25)
        except asyncio.TimeoutError:
            return count
        return count

    monkeypatch.setattr(sources, "_capacity", capacity)

    async def upload(number):
        async with file_database() as db:
            await sources.upload(
                db,
                "quota-owner",
                "quota-session",
                filename=f"{number}.md",
                content=f"Coastal record {number}.",
                format="md",
            )
            await db.commit()

    results = await asyncio.gather(upload(1), upload(2), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    rejected = [result for result in results if isinstance(result, WorldInfoError)]
    assert len(rejected) == 1 and rejected[0].status == 413
    async with file_database() as db:
        assert len(list(await db.scalars(select(WorldInfoSource.id)))) == 1


async def test_source_writes_preserve_session_timestamps_and_owned_gameplay_fields(file_database):
    async with file_database() as db:
        session = await db.get(GameSession, "quota-session")
        previous = (
            session.created_at,
            session.updated_at,
            session.status,
            session.playtime_seconds,
        )
        source, _, _ = await sources.upload(
            db,
            "quota-owner",
            "quota-session",
            filename="notes.md",
            content="First coastal record.",
            format="md",
        )
        await db.commit()
        await db.refresh(session)
        assert (
            session.created_at,
            session.updated_at,
            session.status,
            session.playtime_seconds,
        ) == previous
        await sources.replace(
            db,
            "quota-owner",
            "quota-session",
            source.id,
            source.version,
            filename="notes.md",
            content="Updated coastal record.",
            format="md",
        )
        await db.commit()
        await sources.remove(db, "quota-owner", "quota-session", source.id, source.version)
        await db.commit()
        await db.refresh(session)
        assert (
            session.created_at,
            session.updated_at,
            session.status,
            session.playtime_seconds,
        ) == previous


async def test_initial_source_write_does_not_authorize_foreign_session(file_database):
    async with file_database() as db:
        with pytest.raises(WorldInfoError) as error:
            await sources.upload(
                db,
                "another-owner",
                "quota-session",
                filename="notes.md",
                content="A coastal record.",
                format="md",
            )
        assert error.value.status == 404
        assert not list(await db.scalars(select(WorldInfoSource.id)))
