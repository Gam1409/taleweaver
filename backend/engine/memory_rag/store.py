"""Optional local LanceDB memory cache with mandatory ownership/generation filters."""

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

from backend.engine.memory_rag.embeddings import validate_vectors
from backend.engine.memory_rag.storage_tasks import mutate_storage
from backend.engine.memory_rag.store_schema import (
    Scope,
    hybrid_rank,
    lexical_filter,
    literal,
    query_filter,
    row,
    schema,
    scope_filter,
    table_name,
)

_WRITE_LOCK = threading.RLock()
MAX_CANDIDATES = 128


def _table_names(connection: Any) -> set[str]:
    names: set[str] = set()
    page = connection.list_tables()
    names.update(page.tables)
    while page.page_token:
        page = connection.list_tables(page_token=page.page_token)
        names.update(page.tables)
    return names


class MemoryStoreUnavailableError(RuntimeError):
    """Optional LanceDB support is unavailable in this installation."""


class LanceMemoryStore:
    def __init__(self, root: Path | str | None = None) -> None:
        default = Path(__file__).resolve().parents[3] / "db" / "lancedb"
        self.root = Path(root or os.environ.get("MEMORY_DB_DIR") or default).resolve()

    def _connect(self) -> Any:
        try:
            import lancedb
        except ImportError as exc:
            raise MemoryStoreUnavailableError(
                "LanceDB is unavailable; run poetry install to install memory storage dependencies."
            ) from exc
        self.root.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(self.root))

    def _table(self, scope: Scope) -> Any | None:
        connection = self._connect()
        name = table_name(scope.signature)
        return connection.open_table(name) if name in _table_names(connection) else None

    async def upsert(self, scope: Scope, documents: list[dict], vectors: list[list[float]]) -> None:
        await mutate_storage(self._upsert, scope, documents, vectors)

    def _upsert(self, scope: Scope, documents: list[dict], vectors: list[list[float]]) -> None:
        validated = validate_vectors(vectors, len(documents))
        if not documents:
            return
        scope_filter(scope)
        rows = [
            row(scope, document, vector)
            for document, vector in zip(documents, validated, strict=True)
        ]
        with _WRITE_LOCK:
            connection = self._connect()
            table = self._open_or_create(connection, scope.signature, len(validated[0]))
            if table.schema.field("vector").type.list_size != len(validated[0]):
                raise ValueError("Embedding dimension differs from the indexed vector space.")
            table.merge_insert(
                ["user_id", "session_id", "epoch", "signature", "id"]
            ).when_matched_update_all().when_not_matched_insert_all().execute(rows)

    @staticmethod
    def _open_or_create(connection: Any, signature: str, dimension: int) -> Any:
        name = table_name(signature)
        if name in _table_names(connection):
            return connection.open_table(name)
        return connection.create_table(name, schema=schema(dimension), exist_ok=True)

    async def query(
        self,
        scope: Scope,
        vector: list[float],
        text: str,
        *,
        layers: list[str] | None = None,
        npc_ids: list[str] | None = None,
        scene_id: str | None = None,
        limit: int = 8,
    ) -> list[dict]:
        predicate = query_filter(scope, layers, npc_ids, scene_id)
        validated = validate_vectors([vector], 1)[0]
        return await asyncio.to_thread(
            self._query, scope, validated, text, predicate, max(1, min(limit, 32))
        )

    def _query(
        self, scope: Scope, vector: list[float], text: str, predicate: str, limit: int
    ) -> list[dict]:
        table = self._table(scope)
        if table is None:
            return []
        if table.schema.field("vector").type.list_size != len(vector):
            raise ValueError("Query vector dimension differs from its indexed vector space.")
        candidates = min(MAX_CANDIDATES, limit * 4)
        vector_rows = (
            table.search(vector).where(predicate, prefilter=True).limit(candidates).to_list()
        )
        lexical_rows = (
            table.search()
            .where(predicate + " AND " + lexical_filter(text))
            .limit(MAX_CANDIDATES)
            .to_list()
        )
        return hybrid_rank(vector_rows, lexical_rows, text, limit)

    async def list_document_hashes(self, scope: Scope) -> dict[str, str]:
        return await asyncio.to_thread(self._document_hashes, scope)

    def _document_hashes(self, scope: Scope) -> dict[str, str]:
        table = self._table(scope)
        if table is None:
            return {}
        records = (
            table.search()
            .where(scope_filter(scope))
            .select(["id", "source_hash"])
            .limit(100_000)
            .to_list()
        )
        return {record["id"]: record["source_hash"] for record in records}

    async def prune(self, scope: Scope, valid_ids: list[str] | set[str]) -> int:
        return await mutate_storage(self._prune, scope, set(valid_ids))

    def _prune(self, scope: Scope, valid_ids: set[str]) -> int:
        with _WRITE_LOCK:
            obsolete = set(self._document_hashes(scope)) - valid_ids
            table = self._table(scope)
            if table is None or not obsolete:
                return 0
            predicate = (
                scope_filter(scope)
                + " AND id IN ("
                + ",".join(literal(value) for value in obsolete)
                + ")"
            )
            table.delete(predicate)
            return len(obsolete)

    async def delete_scope(self, scope: Scope) -> int:
        return await mutate_storage(self._delete, scope_filter(scope), table_name(scope.signature))

    async def prune_generations(self, scope: Scope) -> int:
        """Remove superseded generations while the caller holds the SQL epoch fence."""
        scope_filter(scope)
        predicate = (
            f"user_id = {literal(scope.user_id)} AND session_id = {literal(scope.session_id)}"
            f" AND (epoch < {scope.epoch} OR"
            f" (epoch = {scope.epoch} AND signature != {literal(scope.signature)}))"
        )
        return await mutate_storage(self._delete, predicate, None)

    async def delete_session(self, user_id: str, session_id: str) -> int:
        predicate = f"user_id = {literal(user_id)} AND session_id = {literal(session_id)}"
        return await mutate_storage(self._delete, predicate, None)

    async def delete_template(self, user_id: str, template_id: str) -> int:
        predicate = f"user_id = {literal(user_id)} AND template_id = {literal(template_id)}"
        return await mutate_storage(self._delete, predicate, None)

    async def count_template(self, user_id: str, template_id: str) -> int:
        predicate = f"user_id = {literal(user_id)} AND template_id = {literal(template_id)}"
        return await asyncio.to_thread(self._count, predicate)

    def _count(self, predicate: str) -> int:
        connection = self._connect()
        names = [name for name in _table_names(connection) if name.startswith("memory_")]
        return sum(connection.open_table(name).count_rows(predicate) for name in names)

    def _delete(self, predicate: str, name: str | None) -> int:
        count = 0
        with _WRITE_LOCK:
            connection = self._connect()
            existing = _table_names(connection)
            names = [name] if name else [item for item in existing if item.startswith("memory_")]
            for table_id in set(names) & existing:
                table = connection.open_table(table_id)
                count += table.count_rows(predicate)
                table.delete(predicate)
        return count
