"""Exercise deletion with the production SQLite connection policy enabled."""

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.database import _set_sqlite_pragmas
from backend.core.relational_delete import delete_owned_rows
from backend.models.base import Base
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.test_living_world import seed


async def test_user_deletion_respects_enabled_foreign_keys_and_keeps_other_users():
    engine = create_async_engine("sqlite+aiosqlite://")
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            assert await db.scalar(text("PRAGMA foreign_keys")) == 1
            db.add(User(id="admin", username="template-owner", hashed_password="test-only"))
            await db.commit()
            user, state = await seed(db)
            survivor = User(username="unrelated-owner", hashed_password="test-only")
            db.add(survivor)
            db.add(
                TurnReplay(
                    session_id=state.session_id, before={}, input_text="test", status="pending"
                )
            )
            await db.commit()
            survivor_id = survivor.id
            await delete_owned_rows(db, User.__table__, User.__table__.c.id == user.id)
            await db.commit()
            await delete_owned_rows(db, User.__table__, User.__table__.c.id == "admin")
            await db.commit()
            assert await db.scalar(select(TurnReplay.session_id)) is None
            assert not (await db.execute(text("PRAGMA foreign_key_check"))).all()
        async with sessions() as db:
            assert await db.get(User, survivor_id) is not None
    finally:
        await engine.dispose()
