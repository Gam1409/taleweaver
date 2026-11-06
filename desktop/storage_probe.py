"""Offline release checks for the bundled SQLite and LanceDB dependencies."""

import asyncio
import sqlite3
from pathlib import Path


def verify(root: Path) -> None:
    database = root / "data/taleweaver.db"
    if database.exists():
        raise ValueError("Storage probes require a fresh disposable profile.")
    verify_resources(root)
    from alembic.script import ScriptDirectory

    from backend.core.database import run_db_migrations

    run_db_migrations()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        actual = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        expected = ScriptDirectory(
            str(Path(__file__).resolve().parents[1] / "alembic")
        ).get_current_head()
        if actual != expected or connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("The bundled SQLite migration/integrity probe failed.")
    asyncio.run(verify_memory(root / "memory"))


def verify_resources(root: Path) -> None:
    from backend.core import generation_sayings, visual_trace
    from backend.core.system_diagnostics import service

    bundle = Path(__file__).resolve().parents[1]
    resources = (
        bundle / "frontend/src/assets/svg/items/chest.svg",
        bundle / "frontend/src/assets/svg/npcs/silhouette.svg",
        generation_sayings._DATA_PATH,
    )
    if any(not path.is_file() for path in resources):
        raise RuntimeError("The distribution is missing bundled gameplay resources.")
    if not service.directory.is_relative_to(root / "logs") or not (
        visual_trace.DIRECTORY.is_relative_to(root / "logs")
    ):
        raise RuntimeError("Desktop diagnostics must use the writable private profile.")


async def verify_memory(root: Path) -> None:
    from backend.engine.memory_rag.store import LanceMemoryStore, Scope

    store = LanceMemoryStore(root)
    scope = Scope("desktop-probe", "disposable-session", 0, "offline-probe")
    document = {
        "id": "probe-document",
        "text": "Persistent scoped memory probe.",
        "source_id": "probe-message",
        "source_hash": "probe-hash",
        "layer": "dialogue",
    }
    # Fixed test vectors exercise native storage without calling an embedding model.
    await store.upsert(scope, [document], [[1.0, 0.0]])
    reopened = LanceMemoryStore(root)
    found = await reopened.query(scope, [1.0, 0.0], "memory probe")
    foreign = await reopened.query(
        Scope("other-user", scope.session_id, 0, scope.signature), [1.0, 0.0], "memory probe"
    )
    if not found or found[0]["id"] != document["id"] or foreign:
        raise RuntimeError("The bundled RAG persistence/isolation probe failed.")
    await reopened.delete_scope(scope)
    if await reopened.list_document_hashes(scope):
        raise RuntimeError("The bundled RAG cleanup probe failed.")
