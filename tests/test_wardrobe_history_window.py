"""History-backed checks must never use future dialogue or silently clip evidence."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.engine.clothing.history import MAX_CHARACTERS, load_history
from backend.engine.clothing.recovery_context import recovery_context
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def test_a_selected_moment_excludes_future_rows_even_with_equal_timestamps():
    async with TestSessionLocal() as db:
        _user, _avatar, state, _prior = await seed_vn(db)
        stamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
        rows = [
            ChatMessage(
                id=f"history-{index}",
                session_id=state.session_id,
                role=role,
                content=text,
                created_at=stamp,
            )
            for index, role, text in [
                (10, "user", "I ask about the coat."),
                (20, "assistant", "Lina removes her coat."),
                (30, "assistant", "Lina puts the coat on again."),
            ]
        ]
        db.add_all(rows)
        await db.flush()
        window = await load_history(db, state.session_id, through=rows[1])
        assert [row["id"] for row in window.messages] == ["history-10", "history-20"]
        assert not window.limited
        assert window.revisions[-1] == (rows[1].id, rows[1].revision_id)
        assert "on again" not in str(window.messages)
        with pytest.raises(ValueError, match="saved narrator"):
            await load_history(db, state.session_id, through=rows[0])
        with pytest.raises(ValueError, match="this session"):
            await load_history(db, "another-session", through=rows[1])


async def test_large_older_message_is_omitted_whole_and_the_limit_is_declared():
    async with TestSessionLocal() as db:
        _user, _avatar, state, _prior = await seed_vn(db)
        old = ChatMessage(
            id="history-10",
            session_id=state.session_id,
            role="assistant",
            content="x" * (MAX_CHARACTERS + 1),
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        target = ChatMessage(
            id="history-20",
            session_id=state.session_id,
            role="assistant",
            content="The coat remains on the chair.",
            created_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
        db.add_all([old, target])
        await db.flush()
        window = await load_history(db, state.session_id, through=target)
        assert window.limited
        assert window.messages == [
            {"id": target.id, "role": "assistant", "content": target.content, "scene_id": "START"}
        ]


async def test_recovery_fingerprint_binds_revision_even_when_text_is_unchanged():
    async with TestSessionLocal() as db:
        _user, avatar, state, prior = await seed_vn(db)
        before = await recovery_context(db, state, avatar, "LINA")
        source = await db.get(ChatMessage, prior)
        source.revision_id = "new-revision"
        await db.flush()
        after = await recovery_context(db, state, avatar, "LINA")
        assert before["messages"] == after["messages"]
        assert before["fingerprint"] != after["fingerprint"]


async def test_recovery_fingerprint_binds_the_base_wardrobe_profile():
    async with TestSessionLocal() as db:
        _user, avatar, state, _prior = await seed_vn(db)
        before = await recovery_context(db, state, avatar, "LINA")
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.visual_profile = {"appearance": {"features": "Updated appearance"}, "worn": []}
        await db.flush()
        after = await recovery_context(db, state, avatar, "LINA")
        assert before["fingerprint"] != after["fingerprint"]
