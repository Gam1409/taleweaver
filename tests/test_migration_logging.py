"""Embedded startup migrations must not silence existing gameplay error loggers."""

import io
import logging
import multiprocessing

from sqlalchemy import create_engine, inspect


def _run_migrations(database_path: str) -> None:
    from backend.core import database

    url = "sqlite+aiosqlite:///" + database_path
    database.settings.DATABASE_URL = url
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    logger = logging.getLogger("backend.api.routes.adventures.gameplay_logic")
    logger.disabled = False
    logger.setLevel(logging.DEBUG)
    handlers_before = list(root.handlers)
    database.run_db_migrations()
    assert not logger.disabled, "Startup migrations disabled gameplay logging"
    assert root.level == logging.DEBUG and root.handlers == handlers_before
    logger.error("gameplay diagnostic after migrations")
    logger.debug("debug diagnostic after migrations")
    assert "gameplay diagnostic after migrations" in stream.getvalue()
    assert "debug diagnostic after migrations" in stream.getvalue()
    engine = create_engine(url.replace("+aiosqlite", ""))
    assert "memory_index_states" in inspect(engine).get_table_names()
    engine.dispose()


def test_real_startup_migrations_preserve_application_logging(tmp_path):
    # Isolate global logging configuration and exercise Windows-compatible spawning.
    process = multiprocessing.get_context("spawn").Process(
        target=_run_migrations, args=(str(tmp_path / "migration.db"),)
    )
    process.start()
    process.join(timeout=60)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("Startup migrations did not finish")
    assert process.exitcode == 0
