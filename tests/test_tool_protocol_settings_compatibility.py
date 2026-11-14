"""Tool protocol settings survive public controls and existing session lifecycles."""

import io
import json
import zipfile

import pytest
from sqlalchemy import func, select

from backend.engine.chpm.state import KEY
from backend.models.npc_notebook import NpcNotebook
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, portrait_world, update

__all__ = ["chpm_world", "portrait_world"]


@pytest.mark.parametrize("protocol", ["auto", "native", "json"])
async def test_protocol_survives_defaults_new_sessions_copy_and_ads(
    auth_client, chpm_world, protocol
):
    preferences = update(
        "live", notebook_enabled=True, agent_steps=3, max_calls_per_turn=9, tool_protocol=protocol
    )["settings"]
    template_path = "/api/adventures/portrait-template"
    defaults = await auth_client.patch(
        template_path, json={"npc_personality_settings": preferences}
    )
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["npc_personality_settings"]["tool_protocol"] == protocol
    assert (await auth_client.get(PATH)).json()["settings"]["mode"] == "off"

    started = await auth_client.post(template_path + "/sessions/start")
    assert started.status_code == 201, started.text
    configured = await auth_client.patch(
        PATH, json={"settings": preferences, "expected_revision": 0}
    )
    assert configured.status_code == 200, configured.text
    copied = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
    assert copied.status_code == 201, copied.text

    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
        assert (
            manifest["session_state"]["entity_states"][KEY]["settings"]["tool_protocol"] == protocol
        )
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("protocol.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    session_ids = [
        "portrait-session",
        started.json()["game_id"],
        copied.json()["game_id"],
        imported.json()["game_id"],
    ]
    for session_id in session_ids:
        loaded = await auth_client.get(f"/api/adventures/{session_id}/chpm")
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["settings"]["tool_protocol"] == protocol
        assert loaded.json()["settings"]["notebook_enabled"] is True
        assert loaded.json()["settings"]["agent_steps"] == 3
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(NpcNotebook)
                .where(NpcNotebook.session_id.in_(session_ids))
            )
            == 0
        )


async def test_legacy_settings_default_to_auto_and_invalid_protocol_is_atomic(
    auth_client, chpm_world
):
    before = (await auth_client.get(PATH)).json()
    assert before["settings"]["tool_protocol"] == "auto"
    invalid = update("shadow")
    invalid["settings"]["tool_protocol"] = "unsupported-protocol"
    response = await auth_client.patch(PATH, json=invalid)
    assert response.status_code == 422
    after = (await auth_client.get(PATH)).json()
    assert after["settings"] == before["settings"]
    assert after["revision"] == before["revision"]
