"""The historical init command must create a migration-tracked database."""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def database_revision(path: Path) -> str | None:
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='alembic_version'"
        ).fetchone()
        if not exists:
            return None
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


async def test_legacy_init_produces_a_database_at_the_migration_head(tmp_path):
    database = tmp_path / "taleweaver.db"
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "backend.init_db",
        cwd=ROOT,
        env={
            **os.environ,
            "DATA_DIR": str(tmp_path),
            "DATABASE_URL": "sqlite+aiosqlite:///" + database.as_posix(),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(child.communicate(), 30)
    assert child.returncode == 0, (out + err).decode()
    assert (
        await asyncio.to_thread(database_revision, database)
        == ScriptDirectory(str(ROOT / "alembic")).get_current_head()
    )
