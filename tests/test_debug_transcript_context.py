"""Debug history remains inspectable without consuming story memory or becoming model input."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures.chat_snapshot import load_chat_history
from backend.engine.gameplay.turn_prompt_layout import _load_memory_window, build_narration_messages
from backend.engine.memory_rag.chronicle import _batch
from backend.engine.memory_rag.documents import collect_documents
from backend.engine.memory_rag.recent import recent_dialogue
from backend.engine.memory_rag.transcript_pages import transcript_messages
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


async def seed(db):
    user, adventure, avatar, state = await _seed_game_context(db)
    state.max_memory_turns = 2
    state.entity_states = {"NPC": {"current_scene_id": "START", "inventory": [{"id": "COAT"}]}}
    rows = []
    for turn in range(7):
        rows.extend(
            [
                (f"u{turn}", "user", f"story user {turn}"),
                (f"a{turn}", "assistant", f"story narrator {turn}"),
            ]
        )
    rows.append(("timing", "system", "[DEBUG: Performance] timing only"))
    for index in range(7):
        rows.extend(
            [
                (f"debug{index}", "user", f"/debug correction {index}"),
                (f"result{index}", "system", "Recovered one item."),
            ]
        )
    rows.extend([("u7", "user", "story user 7"), ("door", "system", "The door opens.")])
    for index, (identifier, role, content) in enumerate(rows):
        db.add(
            ChatMessage(
                id=identifier,
                session_id=state.session_id,
                role=role,
                content=content,
                created_at=datetime(2026, 1, 1) + timedelta(seconds=index),
            )
        )
    await db.commit()
    return user, adventure, avatar, state, len(rows)


@pytest.mark.asyncio
async def test_both_prompt_windows_count_real_actions_and_preserve_canonical_state():
    async with TestSessionLocal() as db:
        _, adventure, _, state, count = await seed(db)
        recent = await recent_dialogue(db, state)
        assert [row["content"] for row in recent] == [
            "story user 6",
            "story narrator 6",
            "story user 7",
            "The door opens.",
        ]
        window = await _load_memory_window(db, state.session_id, 1)
        assert [row.id for row in window] == ["u6", "a6", "u7", "door"]
        state.max_memory_turns = 1
        prompts, _ = await build_narration_messages(
            db, state, adventure, "Narration rules", "story user 7"
        )
        combined = "\n".join(row["content"] for row in prompts)
        assert "story narrator 6" in combined and "The door opens." in combined
        assert (
            "/debug" not in combined
            and "Recovered one item" not in combined
            and "timing only" not in combined
        )
        assert state.entity_states["NPC"]["inventory"] == [{"id": "COAT"}]
        assert await db.scalar(select(func.count()).select_from(ChatMessage)) == count


@pytest.mark.asyncio
async def test_chronicle_and_semantic_sources_exclude_debug_without_compressing_active_story(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        user, _, _, state, _ = await seed(db)
        batch = await _batch(db, state)
        assert batch is not None
        assert "story narrator 5" in batch["events"]
        assert "story narrator 6" not in batch["events"]
        assert "/debug" not in batch["events"]
        monkeypatch.setattr("backend.engine.memory_rag.transcript_pages.PAGE_SIZE", 2)
        messages = await transcript_messages(db, state.session_id)
        assert set(messages) == {*(f"u{i}" for i in range(8)), *(f"a{i}" for i in range(7))}
        documents = await collect_documents(db, state, user.id)
        assert documents and not any("/debug" in row.text for row in documents)
        from backend.engine.memory_rag.recall_sources import collect_documents as recall_documents

        recalled = await recall_documents(
            db, state, user.id, candidates=[{"source_message_ids": ["debug0", "a0"]}]
        )
        assert any("a0" in row.source_message_ids for row in recalled)
        assert not any("debug0" in row.source_message_ids for row in recalled)


@pytest.mark.asyncio
async def test_explicitly_flagged_unprefixed_generation_cannot_become_social_scene_evidence():
    from types import SimpleNamespace

    from backend.engine.visual_novel.social import _scene_evidence

    async with TestSessionLocal() as db:
        _, _, _, state, _ = await seed(db)
        db.add(
            ChatMessage(
                id="generated-debug",
                session_id=state.session_id,
                role="assistant",
                content="Generated item diagnostic.",
                is_debug=True,
                created_at=datetime(2026, 1, 2),
            )
        )
        await db.commit()
        source_id, content = await _scene_evidence(SimpleNamespace(db=db, state=state))
        assert source_id == "a6" and content == "story narrator 6"


@pytest.mark.asyncio
async def test_reloaded_legacy_debug_responses_are_marked_without_deleting_history():
    async with TestSessionLocal() as db:
        _, _, _, state, count = await seed(db)
        history = await load_chat_history(db, state.session_id)
        assert len(history) == count
        by_id = {row["id"]: row for row in history}
        assert by_id["debug0"].get("is_debug") is True
        assert by_id["result0"].get("is_debug") is True
        assert by_id["timing"].get("is_debug") is True
        assert not by_id["u7"].get("is_debug") and not by_id["door"].get("is_debug")


def test_debug_flag_survives_client_projection():
    message = ChatMessage(
        session_id="S", role="assistant", content="Generated diagnostic result.", is_debug=True
    )
    assert message.to_client_dict()["is_debug"] is True


def test_legacy_debug_association_ends_after_its_reply_and_preserves_following_game_events():
    from backend.engine.debug_transcript import without_debug

    rows = [
        {"role": "user", "content": "/debug on"},
        {"role": "system", "content": "Enabled."},
        {"role": "system", "content": "The bridge opens."},
        {"role": "assistant", "content": "Lina watches the bridge."},
    ]
    assert without_debug(rows) == rows[2:]
