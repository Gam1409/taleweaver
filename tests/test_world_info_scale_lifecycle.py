"""Ten thousand grouped records survive real independent copy and chunked ADS."""

import io
import json
import zipfile
from collections import Counter

import pytest
from sqlalchemy import func, select

from backend.engine import archive_safety
from backend.engine.world_info.archive_parts import FORMAT
from backend.engine.world_info.portable_schema import PortableWorldInfo
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_fixture import seed_corpus
from tests.world_info_scale_fixture import GROUPS, scale_corpus

__all__ = ["portrait_world"]


@pytest.mark.parametrize("count", [10, 10_000])
async def test_grouped_records_copy_export_and_import_without_loss(
    auth_client, portrait_world, count
):
    payload = scale_corpus(count)
    PortableWorldInfo.model_validate(payload)
    original_ids = {row["id"] for row in payload["entries"]}
    original_hashes = {row["content_hash"] for row in payload["revisions"]}
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        await seed_corpus(db, "portrait-session", owner, payload)
        await db.commit()
    copied = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200, exported.text[:500]
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        archive_safety.validate_archive(archive)
        section = json.loads(archive.read("session.json"))["world_info"]
        if count == 10_000:
            assert section["format"] == FORMAT and section["counts"]["entries"] == count
            assert 1 < len(section["parts"]) <= 128
            assert all(
                archive.getinfo(part["path"]).compress_type == zipfile.ZIP_STORED
                for part in section["parts"]
            )
            assert all(part["bytes"] < archive_safety.MAX_ENTRY_BYTES for part in section["parts"])
        else:
            assert "format" not in section and len(section["entries"]) == count
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("archive-corpus.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    identities = [original_ids]
    async with TestSessionLocal() as db:
        for session_id in (copy_id, imported.json()["game_id"]):
            entries = list(
                await db.scalars(
                    select(WorldInfoEntry).where(WorldInfoEntry.session_id == session_id)
                )
            )
            assert len(entries) == count and all(row.user_id == owner for row in entries)
            current_ids = {row.id for row in entries}
            assert all(current_ids.isdisjoint(previous) for previous in identities)
            identities.append(current_ids)
            groups = (
                await db.execute(
                    select(WorldInfoEntry.group_name, func.count())
                    .where(WorldInfoEntry.session_id == session_id)
                    .group_by(WorldInfoEntry.group_name)
                )
            ).all()
            assert dict(groups) == Counter(GROUPS[index % len(GROUPS)] for index in range(count))
            related = next(row for row in entries if row.relations)
            assert related.relations[0]["target_id"] in current_ids
            assert all("archive" in row.tags for row in entries)
            hashes = set(
                await db.scalars(
                    select(WorldInfoRevision.content_hash).where(
                        WorldInfoRevision.session_id == session_id
                    )
                )
            )
            assert hashes == original_hashes
