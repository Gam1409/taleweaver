"""One current private JSON document per NPC; callers own the accepted turn commit."""

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select, update

from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook.codec import MAX_BYTES, canonicalize
from backend.models.game_session import GameSession
from backend.models.npc_notebook import NpcNotebook
from backend.models.world_entity import WorldEntity

MAX_NOTEBOOKS = 32
MAX_CORPUS_BYTES = MAX_NOTEBOOKS * MAX_BYTES


@dataclass(frozen=True)
class NotebookSnapshot:
    payload: bytes = b"{}"
    revision: int = 0


async def owned(db: Any, session_id: str, owner_id: str) -> None:
    owner = await db.scalar(select(GameSession.user_id).where(GameSession.id == session_id))
    if owner != owner_id:
        raise ChpmError("Notebook session is unavailable.")


async def owned_npc(db: Any, session_id: str, npc_id: str, owner_id: str) -> None:
    await owned(db, session_id, owner_id)
    if not await npc_present(db, session_id, npc_id):
        raise ChpmError("Notebook NPC is unavailable in this session.")


async def npc_present(db: Any, session_id: str, npc_id: str) -> bool:
    actor = await db.scalar(
        select(WorldEntity.pk)
        .where(
            WorldEntity.session_id == session_id,
            WorldEntity.id == npc_id,
            WorldEntity.entity_type == "NPC",
        )
        .limit(1)
    )
    return actor is not None


async def reserve_write(db: Any, session_id: str, owner_id: str) -> None:
    """Acquire the owner-scoped writer before reading creation/CAS capacity."""
    with db.no_autoflush:
        reserved = await db.execute(
            update(GameSession)
            .where(GameSession.id == session_id, GameSession.user_id == owner_id)
            .values(id=GameSession.id, updated_at=GameSession.updated_at)
            .returning(GameSession.id)
            .execution_options(synchronize_session=False)
        )
    if reserved.scalar_one_or_none() is None:
        raise ChpmError("Notebook session is unavailable.")


def checked_payload(row: Any) -> bytes:
    payload = bytes(row.payload)
    if len(payload) != row.byte_size or hashlib.sha256(payload).hexdigest() != row.sha256:
        raise ChpmError("Notebook payload integrity check failed.")
    if canonicalize(payload) != payload:
        raise ChpmError("Notebook document is not canonical JSON.")
    return payload


def _query(session_id: str, npc_id: str, owner_id: str) -> Select[tuple[NpcNotebook]]:
    return select(NpcNotebook).where(
        NpcNotebook.session_id == session_id,
        NpcNotebook.npc_id == npc_id,
        NpcNotebook.user_id == owner_id,
    )


async def load_snapshot(db: Any, mind: Any, owner_id: str) -> NotebookSnapshot:
    scope = mind.genesis.scope
    await owned_npc(db, scope.world_id, scope.observer_id, owner_id)
    row = await db.scalar(
        _query(scope.world_id, scope.observer_id, owner_id).execution_options(
            populate_existing=True
        )
    )
    if row is None:
        return NotebookSnapshot()
    return NotebookSnapshot(checked_payload(row), row.revision)


async def load_payload(db: Any, mind: Any, owner_id: str) -> bytes:
    return (await load_snapshot(db, mind, owner_id)).payload


async def persist_workspace(db: Any, mind: Any, workspace: Any, *, owner_id: str) -> None:
    """Replace one document with compare-and-swap; never commit or retain an old copy."""
    scope = mind.genesis.scope
    await owned_npc(db, scope.world_id, scope.observer_id, owner_id)
    if not workspace.changed:
        return
    payload = workspace.canonical_bytes
    if canonicalize(payload) != payload:
        raise ChpmError("Notebook document is not canonical JSON.")
    values = {
        "payload": payload,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "revision": workspace.revision,
    }
    await reserve_write(db, scope.world_id, owner_id)
    await owned_npc(db, scope.world_id, scope.observer_id, owner_id)
    row = await db.scalar(
        _query(scope.world_id, scope.observer_id, owner_id).execution_options(
            populate_existing=True
        )
    )
    if row is not None:
        changed = await db.execute(
            update(NpcNotebook)
            .where(NpcNotebook.id == row.id, NpcNotebook.revision == workspace.base_revision)
            .values(**values)
            .returning(NpcNotebook.id)
            .execution_options(synchronize_session=False)
        )
        if changed.scalar_one_or_none() is None:
            raise ChpmError("Notebook changed while this turn was being prepared.")
        return
    if workspace.base_revision != 0:
        raise ChpmError("Notebook changed while this turn was being prepared.")
    count = await db.scalar(
        select(func.count())
        .select_from(NpcNotebook)
        .where(NpcNotebook.session_id == scope.world_id)
    )
    if count >= MAX_NOTEBOOKS:
        raise ChpmError("The session notebook capacity is full; existing notes were kept.")
    db.add(
        NpcNotebook(user_id=owner_id, session_id=scope.world_id, npc_id=scope.observer_id, **values)
    )
    await db.flush()
