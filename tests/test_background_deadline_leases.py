"""A long configured LLM request must not outlive its durable task claim."""

import time

from backend.engine.memory_rag import worker as memory
from backend.engine.npc_journal import worker as journal
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


async def test_journal_claim_covers_configured_llm_deadline(journal_world, monkeypatch):
    owner, _ = journal_world
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    message_id = await save_message()
    started = time.time()
    prepared = await journal._prepare(message_id, owner)
    assert prepared is not None
    assert prepared[2]["lease_until"] >= started + 600 + journal.queue.LEASE_SECONDS
    assert await journal._prepare(message_id, owner) is None


async def test_memory_claim_covers_configured_llm_deadline(journal_world, monkeypatch):
    owner, _ = journal_world
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        await memory.mark_dirty(db, session.id, owner, session.template_id)
        await db.commit()
    started = time.time()
    claim = await memory._claim("portrait-session", owner)
    assert claim is not None
    from backend.models.memory_rag import MemoryIndexState

    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        assert row.lease_until >= started + 600 + memory.LEASE_SECONDS
    assert await memory._claim("portrait-session", owner) is None
