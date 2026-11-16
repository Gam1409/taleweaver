"""Real SQLite ownership trees survive copy and both ADS layouts with chat."""

import io
import json
import zipfile
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from backend.api.routes.adventures.sessions import copy_session
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.world_info import archive_parts
from backend.engine.world_info.portability import export_world_info
from backend.models.chat import ChatMessage
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision, WorldInfoSource
from tests.test_session_export_snapshot import snapshot_world
from tests.world_info_fixture import seed_corpus
from tests.world_info_scale_fixture import scale_corpus

__all__ = ["snapshot_world"]


def reference_corpus(count):
    payload = scale_corpus(count)
    payload["entries"][1].update(
        audience="restricted",
        known_by=["EXISTING_GUIDE", "MISSING_GUIDE"],
        unresolved_known_by=["MISSING_GUIDE"],
    )
    source, first = payload["sources"][0], payload["revisions"][0]
    replacement = deepcopy(first)
    replacement.update(
        id=str(uuid4()),
        number=2,
        cursor=0,
        status="processing",
        processed_characters=0,
        facts_count=0,
        entries_count=0,
    )
    source.update(current_revision=2, version=2)
    payload["revisions"].append(replacement)
    return payload


@pytest.mark.parametrize(("count", "force_parts"), [(10, False), (10, True), (10_000, False)])
async def test_fk_enforced_copy_and_ads_preserve_chat_links_and_dormant_scopes(
    snapshot_world, monkeypatch, count, force_parts
):
    sessions, sid, owner, _ = snapshot_world
    if force_parts:
        monkeypatch.setattr(archive_parts, "INLINE_LIMIT_BYTES", 1024)
    payload = reference_corpus(count)
    async with sessions() as db:
        await db.execute(delete(WorldInfoSource).where(WorldInfoSource.session_id == sid))
        await seed_corpus(db, sid, owner, payload)
        replacement = await db.get(WorldInfoRevision, payload["revisions"][-1]["id"])
        replacement.run_token = "fictional-run"
        replacement.lease_token = "fictional-lease"
        replacement.lease_until = 9999999999.0
        await db.commit()
        copied = await copy_session(sid, db, await db.get(User, owner))
        copied_id = copied["game_id"]
    async with sessions() as db:
        wire = await SessionExporter.export_ads(db, copied_id)
    with zipfile.ZipFile(io.BytesIO(wire)) as archive:
        section = json.loads(archive.read("session.json"))["world_info"]
        uses_parts = section.get("format") == archive_parts.FORMAT
        assert uses_parts is (force_parts or count == 10_000)
    async with sessions() as db:
        imported_id = await SessionImporter.import_ads(db, wire, owner)
        assert imported_id is not None
    identities = [{row["id"] for row in payload["entries"]}]
    async with sessions() as db:
        for target in (copied_id, imported_id):
            exported = await export_world_info(db, target, owner)
            assert len(exported["entries"]) == count
            ids = {row["id"] for row in exported["entries"]}
            assert all(ids.isdisjoint(previous) for previous in identities)
            identities.append(ids)
            restricted = next(row for row in exported["entries"] if row["audience"] == "restricted")
            assert restricted["known_by"] == ["EXISTING_GUIDE", "MISSING_GUIDE"]
            assert restricted["unresolved_known_by"] == ["MISSING_GUIDE"]
            linked = next(row for row in exported["entries"] if row["relations"])
            assert linked["relations"][0]["target_id"] in ids
            stopped = next(row for row in exported["revisions"] if row["number"] == 2)
            assert stopped["status"] == "cancelled"
            job = await db.get(WorldInfoRevision, stopped["id"])
            assert job.run_token is job.lease_token is job.lease_until is None
            assert {row["content_hash"] for row in exported["revisions"]} == {
                row["content_hash"] for row in payload["revisions"]
            }
            replies = list(
                await db.scalars(select(ChatMessage).where(ChatMessage.session_id == target))
            )
            assert len(replies) == 1 and replies[0].content == "Original reply."
