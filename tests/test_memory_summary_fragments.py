"""Fragment summaries cover long scenes, survive imports, and share the recent-turn boundary."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.engine.memory_rag import summaries
from backend.engine.memory_rag.chronicle import _batch
from backend.engine.memory_rag.documents import collect_documents, sources_hash, summary_sources
from backend.engine.memory_rag.lifecycle import export_summaries, import_summaries
from backend.engine.memory_rag.recent import recent_dialogue
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


async def test_long_single_message_is_covered_in_bounded_persisted_parts(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    message_id = await save_message("Opening. " + "A scene continues. " * 1800 + " FINAL_PROMISE")
    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="An episode summary")
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        user = SimpleNamespace(id=owner)
        session = await db.get(GameSession, state.session_id)
        session.content_language = "Russian"
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=owner, epoch=0, lease_token="lease"
            )
        )
        await db.commit()
        for _ in range(20):
            if not await summaries.summarize_one_group(
                db, user, state, epoch=0, lease_token="lease"
            ):
                break
        else:
            raise AssertionError("Summary processing did not terminate")
        rows = list(await db.scalars(select(MemorySummary)))
        assert len(rows) > 2
        documents = await collect_documents(db, state, owner)
        sources = summary_sources(documents, "story_summary", None, None)
        covered = [key for row in rows if row.layer == "story_summary" for key in row.source_keys]
        assert len(covered) == len(set(covered))
        assert set(covered) == {doc.source_id for doc in sources}
        prompts = [
            call.kwargs["user_prompt"] for call in model.aexecute_simple_task.await_args_list
        ]
        assert all(len(prompt) <= summaries.MAX_INPUT_CHARS for prompt in prompts)
        assert any("FINAL_PROMISE" in prompt for prompt in prompts)
        assert "Russian" in model.aexecute_simple_task.await_args.kwargs["system_prompt"]
        # Export/import maps fragment keys to the copied message, not its old UUID.
        exported = await export_summaries(db, state.session_id)
        original = await db.get(ChatMessage, message_id)
        copied = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content=original.content,
            scene_id=original.scene_id,
        )
        db.add(copied)
        await db.flush()
        await import_summaries(db, state, owner, exported, {message_id: copied.id})
        await db.commit()
        imported = list(
            await db.scalars(
                select(MemorySummary).where(MemorySummary.id.not_in([row.id for row in rows]))
            )
        )
        assert len(imported) == len(rows)
        assert all(key.startswith(copied.id + ":") for row in imported for key in row.source_keys)
        original.content = "Corrected story"
        await db.commit()
        current = await collect_documents(db, state, owner)
        assert not ({row.id for row in rows} & {doc.source_id for doc in current})
        assert {row.id for row in imported} <= {doc.source_id for doc in current}


async def test_recent_context_and_chronicle_partition_complete_turns(journal_world):
    owner, _ = journal_world
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.max_memory_turns = 3
        start = datetime(2026, 1, 1)
        for turn in range(9):
            for offset, role in enumerate(("user", "system", "system", "assistant")):
                db.add(
                    ChatMessage(
                        session_id=state.session_id,
                        role=role,
                        content=f"{role}-{turn}-{offset}",
                        created_at=start + timedelta(seconds=turn * 4 + offset),
                    )
                )
        await db.commit()
        recent = await recent_dialogue(db, state)
        assert len(recent) == 12
        assert recent[0]["content"] == "user-6-0"
        assert recent[-1]["content"] == "assistant-8-3"
        history = await _batch(db, state)
        assert history is not None
        assert "assistant-5-3" in history["events"]
        assert "user-6-0" not in history["events"]
        state.max_memory_turns = 5
        await db.commit()
        longer = await recent_dialogue(db, state)
        assert len(longer) == 20  # No hidden twelve-message crop.
        assert longer[0]["content"] == "user-4-0"


def test_missing_fragment_invalidates_summary_and_legacy_hash_stays_supported():
    from tests.test_memory_rag_retrieval import document

    first, second = document("one"), document("two")
    legacy = sources_hash([first, second], ["one"])
    assert legacy == sources_hash([first], ["one"], ["one"])
    assert sources_hash([first], ["one", "two"], ["one", "two"]) == ""
