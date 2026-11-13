"""Optional semantic hits cannot evict current NPCs from canonical recall loading."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.memory_rag import retrieval
from backend.engine.memory_rag.recall_sources import MAX_NPCS, _npcs, collect_documents
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.fixture
async def crowded_cast(portrait_world):
    async with TestSessionLocal() as db:
        message = ChatMessage(
            session_id="portrait-session", role="assistant", content="Zara likes mint tea."
        )
        db.add(message)
        await db.flush()
        db.add_all(
            [
                WorldEntity(
                    id=f"A_{index:02}",
                    session_id="portrait-session",
                    entity_type="NPC",
                    name=f"Remote {index}",
                    description="Remote",
                    current_scene_id="FOREST",
                )
                for index in range(21)
            ]
        )
        db.add(
            WorldEntity(
                id="Z_PRESENT",
                session_id="portrait-session",
                entity_type="NPC",
                name="Zara",
                description="Present",
                current_scene_id="TOWER",
                metadata_json={
                    "npc_journal": {
                        "entries": [
                            {
                                "id": "tea",
                                "message_id": message.id,
                                "text": "Likes mint tea",
                                "evidence": "Zara likes mint tea.",
                                "category": "preference",
                                "source": "observed",
                            }
                        ]
                    }
                },
            )
        )
        await db.commit()
        return [{"npc_id": f"A_{index:02}"} for index in range(21)]


@pytest.mark.parametrize("semantic", [False, True])
async def test_present_cast_is_reserved_before_semantic_candidates(crowded_cast, semantic):
    async with TestSessionLocal() as db:
        candidates = crowded_cast if semantic else []
        rows = await _npcs(db, "portrait-session", {"Z_PRESENT"}, candidates)
        assert len(rows) == MAX_NPCS
        assert rows[0].id == "Z_PRESENT"
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        user_id = (await db.get(GameSession, state.session_id)).user_id
        documents = await collect_documents(
            db, state, user_id, npc_ids={"Z_PRESENT"}, candidates=candidates
        )
        assert any(doc.npc_id == "Z_PRESENT" and "mint tea" in doc.text for doc in documents)
        assert await collect_documents(db, state, "foreign-user", npc_ids={"Z_PRESENT"}) == []


async def test_vector_outage_and_hits_keep_the_same_present_working_memory(
    crowded_cast, monkeypatch
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        user_id = (await db.get(GameSession, state.session_id)).user_id
        manager = SimpleNamespace(db=db, state=state, user=SimpleNamespace(id=user_id))
        for candidates in [[], crowded_cast]:
            monkeypatch.setattr(
                retrieval, "_turn_vectors", AsyncMock(return_value=(candidates, None))
            )
            recall = await retrieval._collect_recall(
                manager, "What tea does Zara like?", {"Z_PRESENT"}
            )
            assert any(doc.npc_id == "Z_PRESENT" for doc in recall.core_documents)


async def test_more_present_than_bound_preserves_cap_and_stable_present_priority(crowded_cast):
    async with TestSessionLocal() as db:
        wanted = {row["npc_id"] for row in crowded_cast} | {"Z_PRESENT"}
        first = await _npcs(db, "portrait-session", wanted, [])
        second = await _npcs(db, "portrait-session", wanted, [{"npc_id": "NPC_NEW"}] * 32)
        assert len(first) == len(second) == MAX_NPCS
        assert [row.id for row in first] == [row.id for row in second]
        assert all(row.id in wanted for row in first)
