"""Rewrites and revision restoration keep presentation attached to its own text."""

import json

import pytest
from sqlalchemy import select

from backend.engine.npc_presentation.settings import KEY
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_narration_regeneration import narration
from tests.test_session_portraits import portrait_world

__all__ = ["narration", "portrait_world"]
PATH = "/api/adventures/portrait-session/chat"


@pytest.mark.parametrize("color_rgb", [None, [140, 160, 210]])
async def test_rewrite_uses_same_call_and_restoring_revision_restores_its_cue(
    auth_client, narration, color_rgb
):
    message_id, llm = narration
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, KEY: {"emotion_palette": True}}
        await db.commit()
    # NPC_NEW is the session-owned actor from the portrait fixture.
    body = "The locked gate refuses to budge."
    cue = {
        "emotion": "anger" if color_rgb is None else "vulnerability",
        "intensity": 60,
        **({"color_rgb": color_rgb} if color_rgb is not None else {}),
    }
    llm.aexecute_simple_task.return_value = (
        body + "<npc-state>" + json.dumps({"npcs": [{"npc_id": "NPC_NEW", **cue}]}) + "</npc-state>"
    )
    result = await auth_client.post(PATH + "/regenerate", json={"message_id": message_id})
    assert result.status_code == 200, result.text
    rewritten = result.json()
    assert rewritten["content"] == body
    assert rewritten["portrait_state"]["npcs"]["NPC_NEW"] == cue
    llm.aexecute_simple_task.assert_awaited_once()
    versions = (await auth_client.get(f"{PATH}/{message_id}/versions")).json()["versions"]
    original_id = versions[0]["id"]
    rewrite_id = versions[1]["id"]
    result = await auth_client.post(
        f"{PATH}/{message_id}/versions/restore",
        json={"version_id": original_id, "expected_revision_id": rewritten["revision_id"]},
    )
    assert result.status_code == 200, result.text
    assert result.json()["portrait_state"] is None
    result = await auth_client.post(
        f"{PATH}/{message_id}/versions/restore",
        json={"version_id": rewrite_id, "expected_revision_id": result.json()["revision_id"]},
    )
    assert result.status_code == 200, result.text
    assert result.json()["portrait_state"] == rewritten["portrait_state"]
