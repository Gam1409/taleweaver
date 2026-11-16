"""Selecting an old source version cannot reactivate unselected saved records."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from backend.engine.world_info import publishing, views
from backend.engine.world_info.schemas import Publish
from backend.engine.world_info.types import EntryDraft, entry_hash
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_fixture import seed_corpus

__all__ = ["portrait_world"]


async def test_historical_acceptance_publishes_only_the_explicit_selection(portrait_world):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        payload = await seed_corpus(db, "portrait-session", user.id)
        replacement = await db.get(WorldInfoRevision, payload["revisions"][1]["id"])
        replacement.status = "review"
        replacement.cursor = 1
        replacement.entries_count = replacement.facts_count = 1
        replacement.processed_characters = replacement.input_characters
        third = deepcopy(payload["entries"][0])
        third.update(
            id=str(uuid4()), source_revision_id=replacement.id, status="draft", relations=[]
        )
        third["facts"][0]["id"] = str(uuid4())
        draft = EntryDraft.model_validate({key: third[key] for key in EntryDraft.model_fields})
        third["content_hash"] = entry_hash(draft)
        db.add(WorldInfoEntry(**third, user_id=user.id, session_id="portrait-session"))
        await db.commit()
        await publishing.publish(
            db,
            user.id,
            "portrait-session",
            Publish(
                revision_id=replacement.id,
                source_version=2,
                entries=[{"id": third["id"], "version": 1}],
            ),
        )
        await db.commit()
        first = await db.get(WorldInfoEntry, payload["entries"][0]["id"], populate_existing=True)
        await publishing.publish(
            db,
            user.id,
            "portrait-session",
            Publish(
                revision_id=payload["revisions"][0]["id"],
                source_version=3,
                entries=[{"id": first.id, "version": first.version}],
            ),
        )
        await db.commit()
        active = await views.list_entries(db, user.id, "portrait-session", view="active")
        assert {row.id for row in active.entries} == {first.id}
