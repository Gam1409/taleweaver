"""Rewound recipient references remain preserved and inert in independent saves."""

import pytest
from sqlalchemy import select

from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.world_info.portability import export_world_info
from backend.engine.world_info.projection import collect_documents, visible_to
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_fixture import corpus, seed_corpus

__all__ = ["portrait_world"]
SID = "portrait-session"
GUIDE = "FUTURE_GUIDE"


def guide(session_id):
    return WorldEntity(
        id=GUIDE,
        session_id=session_id,
        entity_type="NPC",
        name="Harbor guide",
        description="A fictional guide.",
        current_scene_id="TOWER",
    )


async def change(client, session_id, entry_id, *, resolve=False):
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry_id)
        payload = {
            key: getattr(row, key)
            for key in (
                "version",
                "title",
                "summary",
                "kind",
                "audience",
                "known_by",
                "tags",
                "relations",
            )
        }
        payload["facts"] = [{"id": fact["id"], "text": fact["text"]} for fact in row.facts]
        payload["summary"] = "Reviewed after copying."
        payload["resolve_known_by"] = [GUIDE] if resolve else []
    response = await client.put(
        f"/api/adventures/{session_id}/world-info/entries/{entry_id}", json=payload
    )
    assert response.status_code == 200, response.text


async def assert_visibility(session_id, owner, entry_id, *, resolved):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        documents = await collect_documents(db, state, owner)
        record = next(doc for doc in documents if doc.source_id == f"world_info:{entry_id}")
        assert visible_to(record, "narrator")
        assert visible_to(record, "actor", actor_id=GUIDE, actual_npc_ids=[GUIDE]) is resolved


async def test_undo_copy_and_ads_keep_missing_recipients_dormant_until_explicit_assignment(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        before = await capture(db, SID)
        db.add(guide(SID))
        payload = corpus()
        payload["entries"][1]["known_by"] = [GUIDE]
        await seed_corpus(db, SID, owner, payload)
        await db.commit()
        await restore(db, SID, before)
        await db.commit()
        original = await db.get(WorldInfoEntry, payload["entries"][1]["id"])
        assert original.known_by == [GUIDE] and original.unresolved_known_by == []
        portable = await export_world_info(db, SID, owner)
        restricted = next(row for row in portable["entries"] if row["audience"] == "restricted")
        assert restricted["unresolved_known_by"] == [GUIDE]
        assert original.unresolved_known_by == []  # Export does not mutate authoring state.
    copied = await auth_client.post(f"/api/adventures/sessions/{SID}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("dormant-guide.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for target in (copy_id, imported.json()["game_id"]):
        async with TestSessionLocal() as db:
            entry = await db.scalar(
                select(WorldInfoEntry).where(
                    WorldInfoEntry.session_id == target, WorldInfoEntry.audience == "restricted"
                )
            )
            entry_id = entry.id
            assert entry.known_by == [GUIDE] and entry.unresolved_known_by == [GUIDE]
            db.add(guide(target))
            await db.commit()
        await assert_visibility(target, owner, entry_id, resolved=False)
        await change(auth_client, target, entry_id)
        await assert_visibility(target, owner, entry_id, resolved=False)
        await change(auth_client, target, entry_id, resolve=True)
        await assert_visibility(target, owner, entry_id, resolved=True)


@pytest.mark.parametrize("unresolved", [["FOREIGN"], [GUIDE, GUIDE]])
def test_unresolved_recipient_metadata_is_a_distinct_subset(unresolved):
    from backend.engine.world_info.portable_schema import PortableWorldInfo

    payload = corpus()
    payload["entries"][1]["unresolved_known_by"] = unresolved
    with pytest.raises(ValueError):
        PortableWorldInfo.model_validate(payload)


async def test_archived_entries_are_retained_in_an_independent_copy(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        payload = corpus()
        payload["entries"][0]["status"] = "archived"
        await seed_corpus(db, SID, owner, payload)
        await db.commit()
    response = await auth_client.post(f"/api/adventures/sessions/{SID}/copy")
    assert response.status_code == 201, response.text
    async with TestSessionLocal() as db:
        copied = await export_world_info(db, response.json()["game_id"], owner)
        assert sorted(row["status"] for row in copied["entries"]) == ["archived", "published"]
        assert copied["sources"][0]["published_revision"] == 1
