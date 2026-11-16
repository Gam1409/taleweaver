"""Observer vectors reach an actual VN proposal, reviewed narration and saved state."""

import json

from backend.engine.chpm import semantic_index, semantic_recall
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.state import KEY, load
from backend.engine.memory_rag.scheduling import IdleScheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore
from backend.engine.memory_rag.worker import Claim
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import configured, roles_for, run


async def test_semantic_evidence_survives_the_complete_live_turn(monkeypatch, tmp_path):
    roles = roles_for(monkeypatch)
    store = LanceMemoryStore(tmp_path)
    monkeypatch.setattr(semantic_index, "LanceMemoryStore", lambda: store)
    monkeypatch.setattr(semantic_recall, "LanceMemoryStore", lambda: store)
    monkeypatch.setattr(semantic_index, "scheduler", IdleScheduler(grace_seconds=0))
    calls = []

    async def embed(user, texts, **kwargs):
        calls.append((texts, kwargs))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic_index, "embed_texts", embed)
    monkeypatch.setattr(semantic_recall, "embed_texts", embed)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        manager, chunks = await run(db, user)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        current = load(manager.state)
        original_identity = current.minds["LINA"].genesis
        row = ChatMessage(
            session_id=manager.game_id,
            role="assistant",
            content="The sealed specimen is in locker 7319.",
            scene_id=state.current_scene_id,
        )
        db.add(row)
        await db.flush()
        current.minds["LINA"] = record(
            current.minds["LINA"],
            Source(
                message_id=row.id,
                revision_id=row.revision_id,
                content_hash=digest(row.content),
                role="assistant",
                speaker_id="LINA",
                kind="narration",
                text=row.content,
            ),
            minute=current.minds["LINA"].snapshot.sim_minute,
        )
        current.settings.semantic_memory = True
        manager.state.entity_states = {**manager.state.entity_states, KEY: current.model_dump()}
        user.llm_settings = {
            **(user.llm_settings or {}),
            "memory_rag": {
                "enabled": True,
                "base_url": "http://localhost:11434",
                "model": "test-embed",
            },
        }
        base = embedding_signature(read_settings(user), 2)
        index = await db.get(MemoryIndexState, manager.game_id)
        index.signature = base
        index.lease_token = "test-token"
        await db.commit()
        assert await semantic_index.index_batch(
            Claim(
                manager.game_id,
                user.id,
                index.epoch,
                index.desired_revision,
                "test-token",
                base,
                False,
            ),
            user,
        )
        before = len(roles.chpm_calls)
        manager, chunks = await run(db, user, "Where did you leave the specimen?")
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        saved = load(manager.state)
        assert saved.minds["LINA"].genesis == original_identity
        assert saved.usage.semantic_recall == {"LINA": "hybrid"}
        assert roles.chpm_calls[before:] == ["perception", "proposal", "validation"]
        assert calls[-1][1]["purpose"] == "query" and len(calls[-1][0]) == 1
        assert "retrieved_episode_context" in roles.proposal_inputs[-1]
        assert "7319" in json.dumps(roles.proposal_inputs[-1])
        evidence = saved.actors["LINA"].agent_evidence
        assert any("7319" in item.text and item.context for item in evidence)
        assert "7319" in json.dumps(roles.prompts[-1])
