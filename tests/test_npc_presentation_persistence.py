"""Session exports, copies and turn checkpoints retain narration-bound cues."""

import pytest
from sqlalchemy import select

from backend.core.npc_presentation import source_hash
from backend.engine.npc_journal.messages import copy_messages, restore_messages
from backend.engine.session_exporter import SessionExporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("color_rgb", [None, [140, 160, 210]])
async def test_session_copy_export_and_import_preserve_cues(portrait_world, color_rgb):
    text = "The sailor breathes calmly."
    cue = {
        "version": 1,
        "source_hash": source_hash(text),
        "npcs": {
            "NPC_NEW": {
                "emotion": "calm" if color_rgb is None else "vulnerability",
                "intensity": 40,
                "thought": "We made it.",
                **({"color_rgb": color_rgb} if color_rgb is not None else {}),
            }
        },
    }
    async with TestSessionLocal() as db:
        message = ChatMessage(
            session_id="portrait-session", role="assistant", content=text, portrait_state=cue
        )
        db.add(message)
        await db.flush()
        manifest = await SessionExporter.build_session_manifest(db, "portrait-session")
        exported = manifest["chat_messages"][0]
        assert exported["portrait_state"] == cue
        copies = await copy_messages(db, "portrait-session", "other-session")
        await db.flush()
        copied = await db.get(ChatMessage, copies[message.id])
        assert copied.id != message.id
        assert copied.session_id == "other-session"
        assert copied.to_client_dict()["portrait_state"] == cue
        imported_ids = restore_messages(db, "portrait-session", [exported])
        await db.flush()
        imported = await db.get(ChatMessage, imported_ids[message.id])
        assert imported.id not in {message.id, copied.id}
        assert imported.to_client_dict()["portrait_state"] == cue
        assert message.content == copied.content == imported.content


async def test_turn_snapshot_captures_new_nullable_column(portrait_world):
    text = "Rin pauses."
    cue = {
        "version": 1,
        "source_hash": source_hash(text),
        "npcs": {"NPC_NEW": {"emotion": "interest", "intensity": 20}},
    }
    async with TestSessionLocal() as db:
        db.add(
            ChatMessage(
                session_id="portrait-session", role="assistant", content=text, portrait_state=cue
            )
        )
        await db.flush()
        snapshot = await capture(db, "portrait-session", backup=True)
        messages = await db.scalars(
            select(ChatMessage).where(ChatMessage.session_id == "portrait-session")
        )
        assert len(messages.all()) == 1
        assert snapshot["messages"][0]["portrait_state"] == cue
        saved_id = snapshot["messages"][0]["id"]
        message = await db.get(ChatMessage, saved_id)
        message.content = "A different outcome."
        message.portrait_state = None
        await db.flush()
        await restore(db, "portrait-session", snapshot)
        restored = await db.get(ChatMessage, saved_id, populate_existing=True)
        assert restored.content == text
        assert restored.to_client_dict()["portrait_state"] == cue
