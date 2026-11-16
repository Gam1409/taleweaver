"""Placement proof belongs to the copied/imported session's own history."""

from copy import deepcopy
from hashlib import sha256

from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_clothing_lifecycle import actors, clothing_world, start

__all__ = ["clothing_world"]
TEXT = "The hero raises the coat; Lina raises the dress."


async def test_copy_import_and_checkpoint_keep_local_wear_sources(auth_client, clothing_world):
    sid = await start(auth_client)
    async with TestSessionLocal() as db:
        avatar, npc, state = await actors(db, sid)
        db.add(ChatMessage(id="wear-source", session_id=sid, role="assistant", content=TEXT))
        proof = {
            "request_id": None,
            "source_message_id": "wear-source",
            "content_hash": sha256(TEXT.encode()).hexdigest(),
            "evidence": TEXT,
        }
        for actor in (avatar, npc):
            raw = deepcopy(actor.visual_profile)
            raw["body"] = {"form": "humanoid", "silhouette": "neutral"}
            raw["worn"][0].update(uncovered_regions=["torso", "arms"], source=proof)
            actor.visual_profile = raw
        state.entity_states = {
            **state.entity_states,
            "LINA": {"visual_profile": deepcopy(npc.visual_profile)},
        }
        await db.commit()
        checkpoint = await SessionCheckpointService.create_checkpoint(db, sid, "manual")
        await db.commit()
        before = deepcopy(state.entity_states)
        state.entity_states = {**state.entity_states, "LINA": {"visual_profile": {"worn": []}}}
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, sid, checkpoint.id)
        await db.commit()
        assert {key: state.entity_states[key] for key in before} == before
        # Restoring a checkpoint intentionally invalidates asynchronous image jobs.
        assert set(state.entity_states) - set(before) == {"__visual_preparation__"}
        assert state.entity_states["__visual_preparation__"]["entries"] == {}
    copy = await auth_client.post(f"/api/adventures/sessions/{sid}/copy")
    assert copy.status_code == 201, copy.text
    export = await auth_client.get(f"/api/adventures/sessions/{sid}/export")
    assert export.status_code == 200, export.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("wear.ads", export.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    async with TestSessionLocal() as db:
        for restored in (copy.json()["game_id"], imported.json()["game_id"]):
            avatar, npc, state = await actors(db, restored)
            for raw in (
                avatar.visual_profile,
                npc.visual_profile,
                state.entity_states["LINA"]["visual_profile"],
            ):
                assert raw["body"]["form"] == "humanoid"
                row = raw["worn"][0]
                assert row["uncovered_regions"] == ["torso", "arms"]
                source = row["source"]
                assert source["source_message_id"] != "wear-source"
                message = await db.get(ChatMessage, source["source_message_id"])
                assert message and message.session_id == restored and message.content == TEXT
