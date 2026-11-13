"""Rewriting reuses current narrator preferences without repeating game actions."""

from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import regeneration_context
from backend.engine.narrator.settings import SETTINGS_KEY
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_narration_regeneration import PATH, narration
from tests.test_session_portraits import portrait_world

__all__ = ["narration", "portrait_world"]


@pytest.mark.asyncio
async def test_rewrite_keeps_selected_voice_length_language_and_original_beat(
    auth_client, narration
):
    message_id, llm = narration
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            SETTINGS_KEY: {
                "voice": {
                    "id": "observant",
                    "name": "Observant",
                    "instruction": "Use restrained close observation and concrete verbs.",
                },
                "verbosity": "terse",
                "flow": "off",
            },
        }
        session = await db.get(GameSession, state.session_id)
        session.content_language = "Russian"
        await db.commit()
        before = deepcopy((await db.execute(select(SessionState.__table__))).mappings().all())
    response = await auth_client.post(
        PATH,
        json={"message_id": message_id, "narration_correction": "Keep the wording direct."},
    )
    assert response.status_code == 200, response.text
    system = llm.aexecute_simple_task.await_args.args[0]
    assert "Use restrained close observation and concrete verbs." in system
    assert "normally one or two short narration sentences" in system
    assert "Recount the original beat, not a new turn" in system
    assert "RUSSIAN" in system.upper()
    assert "Keep the wording direct." in system
    assert "Preserve formatting, speaker identifiers and valid voice-tag syntax" in system
    assert response.json()["id"] == message_id
    llm.aexecute_simple_task.assert_awaited_once()
    async with TestSessionLocal() as db:
        assert (await db.execute(select(SessionState.__table__))).mappings().all() == before


@pytest.mark.asyncio
async def test_rewrite_style_evidence_uses_loaded_current_completed_history_only(
    auth_client, narration, monkeypatch
):
    message_id, llm = narration
    observed = []

    def guidance(_state, narrations, *, language=None):
        observed.append((list(narrations), language))
        return "NARRATION FLOW CHECK: Use fresh concrete openings when appropriate."

    monkeypatch.setattr(regeneration_context, "flow_guidance", guidance)
    async with TestSessionLocal() as db:
        target = await db.get(ChatMessage, message_id)
        records = [
            (
                "assistant",
                "A current older reply.",
                {"versions": [{"content": "An obsolete version."}]},
            ),
            ("assistant", "A debug-only narration.", {"is_debug": True}),
            ("assistant", "An unfinished fragment.", {"npc_journal": {"status": "incomplete"}}),
            ("user", "A player action.", {}),
        ]
        for index, (role, content, fields) in enumerate(records):
            db.add(
                ChatMessage(
                    session_id="portrait-session",
                    role=role,
                    content=content,
                    created_at=target.created_at - timedelta(seconds=10 - index),
                    **fields,
                )
            )
        db.add(
            ChatMessage(
                session_id="other-session", role="assistant", content="A foreign narration."
            )
        )
        await db.commit()
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 200, response.text
    assert observed == [(["A current older reply.", "The gate remains locked."], "English")]
    system = llm.aexecute_simple_task.await_args.args[0]
    assert system.count("NARRATION FLOW CHECK:") == 1
    assert "An obsolete version." not in str(llm.aexecute_simple_task.await_args)
    assert "A foreign narration." not in str(llm.aexecute_simple_task.await_args)
    llm.aexecute_simple_task.assert_awaited_once()
