"""Private core diagnostics and replay baselines survive settings switches safely."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import KEY
from backend.engine.turn_replay.snapshot import capture
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, portrait_world, update
from tests.test_chpm_host_state import mind, record, source

__all__ = ["chpm_world", "portrait_world"]


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_settings_never_copy_future_core_into_retry_baseline(auth_client, chpm_world, mode):
    assert (await auth_client.patch(PATH, json=update("live"))).status_code == 200
    core = record(mind("NPC_NEW", "portrait-session"), source(), minute=1)
    async with TestSessionLocal() as db:
        before = await capture(db, "portrait-session")
        db.add(
            TurnReplay(
                session_id="portrait-session", before=before, input_text="Hello", status="ready"
            )
        )
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        value = deepcopy(state.entity_states)
        value[KEY]["minds"] = {"NPC_NEW": core.model_dump(mode="json")}
        state.entity_states = value
        await db.commit()
    response = await auth_client.patch(PATH, json=update(mode, revision=1, max_output_tokens=1500))
    assert response.status_code == 200, response.text
    assert response.json()["psychology"]["NPC_NEW"]["genesis"] == core.genesis.model_dump(
        mode="json"
    )
    async with TestSessionLocal() as db:
        replay = await db.get(TurnReplay, "portrait-session")
        assert replay.before["state"]["entity_states"][KEY]["minds"] == {}
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.role = "user"
        await db.commit()
    response = await auth_client.get(PATH)
    assert response.json()["psychology"] == {}
    assert response.json()["psychology_counts"] == {"NPC_NEW": {"observations": 1, "beliefs": 0}}
    assert response.json()["history_capacity"]["NPC_NEW"]["used"]["events"] == 1
    assert response.json()["history_capacity"]["NPC_NEW"]["status"] == "ready"
    assert "Independent engineer" not in response.text
