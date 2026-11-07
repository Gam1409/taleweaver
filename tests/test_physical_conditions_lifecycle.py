"""Real copy/export/import endpoints remap physical evidence into the owned save."""

import pytest
from sqlalchemy import select

from backend.engine.physical_conditions.ledger import apply, read
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_physical_conditions import record
from tests.test_session_authored_fields import TEMPLATE, seed_template


@pytest.mark.asyncio
async def test_copy_and_ads_roundtrip_preserve_conditions_with_local_message_anchors(
    auth_client, monkeypatch, tmp_path
):
    await seed_template(monkeypatch, tmp_path, "vn", "template")
    response = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert response.status_code == 201, response.text
    source_id = response.json()["game_id"]
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == source_id))
        message = ChatMessage(
            session_id=source_id, role="assistant", content="Rin has an open neck wound."
        )
        db.add(message)
        await db.flush()
        state.entity_states, _, errors = apply(
            state.entity_states,
            [record(target_id="__player__")],
            targets={"__player__"},
            narration=message.content,
            message_id=message.id,
            session_id=source_id,
            minute=0,
        )
        assert not errors
        original_message = message.id
        await db.commit()
    copied = await auth_client.post(f"/api/adventures/sessions/{source_id}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("physical.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    ids = []
    async with TestSessionLocal() as db:
        for session_id in (source_id, copy_id, imported.json()["game_id"]):
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == session_id)
            )
            ledger = read(state.entity_states)
            condition = next(iter(ledger.conditions.values()))
            assert condition.target_id == "__player__" and condition.detail == "An open neck wound."
            message = await db.get(ChatMessage, condition.origin.message_id)
            assert message.session_id == session_id and condition.origin.quote in message.content
            assert condition.latest.message_id == message.id == ledger.events[0].source.message_id
            assert ledger.last_check["message_id"] == message.id
            ids.append(message.id)
    assert ids[0] == original_message and len(set(ids)) == 3
