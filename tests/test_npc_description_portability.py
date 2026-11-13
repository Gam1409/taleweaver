"""Copied observed descriptions retract with the destination's rewritten reply."""

import pytest
from sqlalchemy import select

from backend.engine.npc_journal.lifecycle import remap_journal
from backend.engine.npc_journal.records import journal_of
from backend.models.chat import ChatMessage
from tests.checkpoint_source_support import (
    ORIGINAL,
    actor,
    check_retracted,
    narration,
    observed_reply,
    portrait_world,
)
from tests.conftest import TestSessionLocal

__all__ = ["narration", "observed_reply", "portrait_world"]


@pytest.mark.parametrize("operation", ["copy", "ads"])
async def test_copied_source_regeneration_clears_derived_description(
    auth_client, observed_reply, operation
):
    original_id, llm = observed_reply
    if operation == "copy":
        copied = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
        assert copied.status_code == 201, copied.text
    else:
        exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
        assert exported.status_code == 200
        copied = await auth_client.post(
            "/api/adventures/sessions/import",
            files={"file": ("session.ads", exported.content, "application/zip")},
        )
        assert copied.status_code == 200, copied.text
    sid = copied.json()["game_id"]
    async with TestSessionLocal() as db:
        npc = await actor(db, sid)
        source_id = journal_of(npc)["introduced_message_id"]
        assert source_id != original_id
        assert journal_of(npc)["description_source"] == source_id
    rewritten = await auth_client.post(
        f"/api/adventures/{sid}/chat/regenerate", json={"message_id": source_id}
    )
    assert rewritten.status_code == 200, rewritten.text
    await check_retracted(sid, source_id)
    async with TestSessionLocal() as db:
        assert (await actor(db)).description == "A blue coat"
        assert (await db.get(ChatMessage, original_id)).content == ORIGINAL
        assert (
            len(list(await db.scalars(select(ChatMessage).where(ChatMessage.session_id == sid))))
            == 2
        )
    llm.aexecute_simple_task.assert_awaited_once()


def test_description_source_remapping_preserves_legacy_fallback_and_source():
    source = {"npc_journal": {"origin": "introduced", "description_source": "old"}}
    remapped = remap_journal(source, {"old": "new"})
    assert remapped["npc_journal"]["description_source"] == "new"
    assert source["npc_journal"]["description_source"] == "old"
    assert remap_journal(source, {})["npc_journal"]["description_source"] == "old"
