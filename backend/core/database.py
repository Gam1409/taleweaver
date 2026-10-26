import logging

from anyio import CancelScope
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Create the async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},  # Needed for SQLite
)


if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        """Reduce lock contention for concurrent background writes + status polling."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


# Async session factory
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Dependency to get session
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # AnyIO cancellation repeats at each await; let rollback/close finish.
            with CancelScope(shield=True):
                await session.close()


def run_db_migrations() -> None:
    """Executes Alembic migrations to upgrade the schema to the latest head revision."""
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s. Skipping auto-migration.", alembic_ini)
        return

    logger.info("Applying Alembic migrations (head)...")
    alembic_cfg = Config(str(alembic_ini))
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations completed successfully.")


async def apply_sqlite_compat_migrations() -> None:
    """Deprecated: Schema migrations are now managed by Alembic. Retained for backwards compatibility."""
    import asyncio

    logger.debug("apply_sqlite_compat_migrations() is deprecated. Running Alembic migrations.")
    await asyncio.to_thread(run_db_migrations)
