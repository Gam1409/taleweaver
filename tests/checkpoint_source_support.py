"""Synthetic observed NPC sources shared by checkpoint and copy regressions."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.npc_journal import worker
from backend.engine.npc_journal.records import journal_of
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_narration_regeneration import narration, portrait_world

__all__ = ["narration", "portrait_world"]

ORIGINAL = "Mira says: I am a smith. She wears a blue coat."
REPLACEMENT = "Mira says: I forge tools for a living. Her coat is blue."


async def actor(db, session_id="portrait-session"):
    return await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == session_id, WorldEntity.id == "NPC_NEW")
    )


@pytest.fixture
async def observed_reply(narration, monkeypatch):
    source_id, llm = narration
    monkeypatch.setattr(worker, "schedule", MagicMock())
    llm.aexecute_simple_task.return_value = REPLACEMENT
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, source_id)
        message.content = ORIGINAL
        message.npc_journal = {"status": "done", "attempts": 1}
        earlier = ChatMessage(
            session_id=message.session_id,
            role="assistant",
            content="Mira likes tea.",
            created_at=message.created_at - timedelta(seconds=1),
        )
        db.add(earlier)
        await db.flush()
        npc = await actor(db)
        npc.description = "A blue coat"
        npc.metadata_json = {
            "npc_journal": {
                "origin": "introduced",
                "introduced_message_id": source_id,
                "description_source": source_id,
                "observed_description": npc.description,
                "aliases": ["Smith"],
                "alias_sources": {"Smith": source_id},
                "entries": [
                    {
                        "id": "appearance",
                        "message_id": source_id,
                        "text": "A blue coat",
                        "evidence": "She wears a blue coat.",
                        "category": "appearance",
                        "source": "observed",
                    },
                    {
                        "id": "profession",
                        "message_id": source_id,
                        "text": "A smith",
                        "evidence": "I am a smith",
                        "category": "background",
                        "source": "claimed",
                    },
                    {
                        "id": "earlier",
                        "message_id": earlier.id,
                        "text": "Likes tea",
                        "evidence": "Mira likes tea.",
                        "category": "preference",
                        "source": "observed",
                    },
                ],
            }
        }
        await db.commit()
    return source_id, llm


async def check_retracted(session_id, source_id):
    async with TestSessionLocal() as db:
        npc = await actor(db, session_id)
        journal = journal_of(npc, full=True)
        assert npc.description == ""
        assert "description_source" not in journal
        assert not journal["aliases"]
        assert [entry["id"] for entry in journal["entries"]] == ["earlier"]
        message = await db.get(ChatMessage, source_id)
        assert message.npc_journal == {"status": "pending", "attempts": 0}
