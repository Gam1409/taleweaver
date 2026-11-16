import asyncio


async def init_db() -> None:
    """Compatibility command: initialize through the same migrations as startup."""
    from backend.core.database import run_db_migrations

    await asyncio.to_thread(run_db_migrations)


if __name__ == "__main__":
    asyncio.run(init_db())
