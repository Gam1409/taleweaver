"""Portable current notebook documents with explicit owner and session rebinding."""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import func, select

from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook.codec import MAX_BYTES, encode
from backend.engine.chpm.notebook_archive import (
    NotebookArchive,
    _encoded,
    append_part,
    create_archive,
    rows,
)
from backend.engine.chpm.notebook_store import (
    MAX_CORPUS_BYTES,
    MAX_NOTEBOOKS,
    checked_payload,
    npc_present,
    owned,
    owned_npc,
    reserve_write,
)
from backend.models.npc_notebook import NpcNotebook


class PortableRow(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    npc_id: str = Field(min_length=1, max_length=100)
    byte_size: StrictInt = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document: Any
    dormant: StrictBool = False


async def export_notebooks(db: Any, state: Any, owner_id: str) -> NotebookArchive | None:
    await owned(db, state.session_id, owner_id)
    corpus = create_archive()
    total = 0
    query = (
        select(NpcNotebook)
        .where(NpcNotebook.session_id == state.session_id, NpcNotebook.user_id == owner_id)
        .order_by(NpcNotebook.npc_id)
        .execution_options(yield_per=1, populate_existing=True)
    )
    try:
        async for row in await db.stream_scalars(query):
            payload = checked_payload(row)
            total += len(payload)
            if total > MAX_CORPUS_BYTES or corpus.rows >= MAX_NOTEBOOKS:
                raise ChpmError("Notebook portable corpus exceeds its budget.")
            encoded = _encoded(
                {
                    "npc_id": row.npc_id,
                    "byte_size": row.byte_size,
                    "sha256": row.sha256,
                    "dormant": not await npc_present(db, state.session_id, row.npc_id),
                },
                payload,
            )
            append_part(corpus, [encoded])
        if not corpus.rows:
            corpus.stream.close()
            return None
        return corpus
    except BaseException:
        corpus.stream.close()
        raise


async def import_notebooks(
    db: Any, state: Any, owner_id: str, corpus: NotebookArchive | None
) -> None:
    if corpus is None:
        return
    try:
        await _import_current(db, state, owner_id, corpus)
    finally:
        corpus.stream.close()


async def _import_current(db: Any, state: Any, owner_id: str, corpus: NotebookArchive) -> None:
    await owned(db, state.session_id, owner_id)
    await reserve_write(db, state.session_id, owner_id)
    existing = await db.scalar(
        select(func.count())
        .select_from(NpcNotebook)
        .where(NpcNotebook.session_id == state.session_id)
    )
    if existing:
        raise ChpmError("Notebook import destination must be empty.")
    seen: set[str] = set()
    total = 0
    for _path, payload in corpus.payloads():
        for item in rows(payload):
            row = PortableRow.model_validate(item)
            if row.npc_id in seen or len(seen) >= MAX_NOTEBOOKS:
                raise ChpmError("Notebook portable NPC membership is invalid.")
            # Rewinds can remove generated NPCs while preserving their current notes.
            # Dormant portable data never grants tools or recreates a world entity.
            if not row.dormant:
                await owned_npc(db, state.session_id, row.npc_id, owner_id)
            document = encode(row.document)
            total += len(document)
            if (
                len(document) != row.byte_size
                or hashlib.sha256(document).hexdigest() != row.sha256
                or total > MAX_CORPUS_BYTES
            ):
                raise ChpmError("Notebook portable payload integrity is invalid.")
            seen.add(row.npc_id)
            db.add(
                NpcNotebook(
                    user_id=owner_id,
                    session_id=state.session_id,
                    npc_id=row.npc_id,
                    revision=0,
                    byte_size=row.byte_size,
                    sha256=row.sha256,
                    payload=document,
                )
            )
            await db.flush()
    if len(seen) != corpus.rows:
        raise ChpmError("Notebook portable payloads are incomplete.")


async def copy_notebooks(db: Any, source: Any, target: Any, owner_id: str) -> None:
    corpus = await export_notebooks(db, source, owner_id)
    await import_notebooks(db, target, owner_id, corpus)
