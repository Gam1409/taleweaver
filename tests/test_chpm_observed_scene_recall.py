"""Post-retrieval canonical reads must include nested scene anchors as well as input IDs."""

from types import SimpleNamespace

import pytest

from backend.engine.chpm import semantic_recall, semantic_sources
from backend.engine.chpm.host_state import before_messages
from backend.engine.memory_rag.store import Scope
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState
from tests.conftest import TestSessionLocal
from tests.test_chpm_observed_scene_lifecycle import completed


@pytest.mark.parametrize("edit_during_lookup", ["unchanged", "same_session", "other_session"])
async def test_memory_lookup_rechecks_the_scene_without_retracting_an_unchanged_anchor(
    monkeypatch, edit_during_lookup
):
    async with TestSessionLocal() as db:
        manager, mind, scene = await completed(db, monkeypatch)
        index = await db.get(MemoryIndexState, manager.game_id)
        assert index
        index.epoch, index.signature, index.paused = 1, "base", False
        await db.commit()

        async def query(*args, **kwargs):
            if edit_during_lookup == "same_session":
                scene.content += " Corrected ending."
                await db.flush()
            elif edit_during_lookup == "other_session":
                async with TestSessionLocal() as writer:
                    changed = await writer.get(ChatMessage, scene.id)
                    changed.content += " Corrected ending."
                    await writer.commit()
            return []

        monkeypatch.setattr(
            semantic_recall, "LanceMemoryStore", lambda: SimpleNamespace(query=query)
        )
        turn = SimpleNamespace(reconciled_minds={})
        scope = Scope(
            manager.user.id,
            manager.game_id,
            1,
            semantic_sources.signature("base"),
            namespace="observer",
        )
        assert (
            await semantic_recall._retrieve(
                manager, turn, "LINA", mind, [1.0, 0.0], "rescue", scope, "base"
            )
            == []
        )
        expected = mind if edit_during_lookup == "unchanged" else before_messages(mind, {scene.id})
        assert turn.reconciled_minds["LINA"] == expected
