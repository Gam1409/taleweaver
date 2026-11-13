"""Ten thousand records are changed on the server without per-record SQL roundtrips."""

from unittest.mock import Mock

from sqlalchemy import event, func, select

from backend.api.routes.adventures import world_info_entries
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal, test_engine
from tests.test_session_portraits import portrait_world
from tests.test_world_info_api import SID, URL
from tests.world_info_scale_fixture import seed_scale

__all__ = ["portrait_world"]


async def test_ten_thousand_record_collection_has_bounded_preview_and_batch_writes(
    auth_client, portrait_world, monkeypatch
):
    monkeypatch.setattr(world_info_entries, "schedule_index", Mock())
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        await seed_scale(db, SID, owner)
        await db.commit()
    statements = []

    def collect(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", collect)
    try:
        body = {
            "action": "set_group",
            "group_name": "Archive index",
            "filters": {"view": "active", "tag": "archive"},
        }
        response = await auth_client.post(URL + "/entries/bulk/preview", json=body)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["count"] == 10_000
        assert len(preview["sample"]) == 5
        assert len(response.content) < 20_000
        statements.clear()
        applied = await auth_client.post(
            URL + "/entries/bulk/apply", json=body | {"selection_hash": preview["selection_hash"]}
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["matched"] == applied.json()["changed"] == 10_000
        updates = [
            statement
            for statement in statements
            if statement.startswith("UPDATE world_info_entries ")
        ]
        assert len(updates) == 1
        assert len(statements) < 40
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", collect)
    async with TestSessionLocal() as db:
        count = await db.scalar(
            select(func.count(WorldInfoEntry.id)).where(
                WorldInfoEntry.session_id == SID, WorldInfoEntry.group_name == "Archive index"
            )
        )
        assert count == 10_000
        versions = set(
            await db.scalars(select(WorldInfoEntry.version).where(WorldInfoEntry.session_id == SID))
        )
        assert versions == {2}
