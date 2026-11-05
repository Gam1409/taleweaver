"""Settings ownership, concurrency, legacy defaults, and snapshot preservation."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import KEY
from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
PATH = "/api/adventures/portrait-session/chpm"


@pytest.fixture
async def chpm_world(portrait_world):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = "vn"
        await db.commit()


def update(mode="shadow", revision=0, **options):
    prefs = Settings(mode=mode, actor_ids=["NPC_NEW"], **options)
    return {"settings": prefs.model_dump(), "expected_revision": revision}


async def test_defaults_selection_and_reversible_disable(auth_client, chpm_world):
    response = await auth_client.get(PATH)
    assert response.status_code == 200
    assert response.json()["settings"]["mode"] == "off"
    assert response.json()["characters"] == [{"id": "NPC_NEW", "name": "Lina"}]
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        original = deepcopy(state.entity_states)
    response = await auth_client.patch(PATH, json=update("live"))
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    response = await auth_client.patch(PATH, json=update("off", revision=1))
    assert response.status_code == 200
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert {k: v for k, v in state.entity_states.items() if k != KEY} == original
        assert state.quests == [{"id": "quest", "status": "active"}]


async def test_foreign_busy_stale_and_unknown_actor_rejected(auth_client, chpm_world):
    assert (await auth_client.get("/api/adventures/other-session/chpm")).status_code == 404
    assert (
        await auth_client.patch("/api/adventures/other-session/chpm", json=update())
    ).status_code == 404
    with session_write_lease("portrait-session"):
        assert (await auth_client.patch(PATH, json=update())).status_code == 409
    bad = update()
    bad["settings"]["actor_ids"] = ["ITEM_1"]
    assert (await auth_client.patch(PATH, json=bad)).status_code == 422
    assert (await auth_client.patch(PATH, json=update())).status_code == 200
    assert (await auth_client.patch(PATH, json=update("live"))).status_code == 409


async def test_non_vn_cannot_enable(auth_client, portrait_world):
    response = await auth_client.patch(PATH, json=update())
    assert response.status_code == 409


async def test_snapshot_restore_includes_chpm_and_settings_update_fences_replay(
    auth_client, chpm_world
):
    assert (await auth_client.patch(PATH, json=update())).status_code == 200
    async with TestSessionLocal() as db:
        saved = await capture(db, "portrait-session")
        db.add(
            TurnReplay(
                session_id="portrait-session", before=saved, input_text="Hello", status="ready"
            )
        )
        await db.commit()
    assert (await auth_client.patch(PATH, json=update("live", revision=1))).status_code == 200
    async with TestSessionLocal() as db:
        replay = await db.get(TurnReplay, "portrait-session")
        assert replay.before["state"]["entity_states"][KEY]["settings"]["mode"] == "live"
        await restore(db, "portrait-session", saved)
        await db.commit()
    response = await auth_client.get(PATH)
    assert response.json()["settings"]["mode"] == "shadow"


async def test_private_trace_is_admin_only(auth_client, chpm_world):
    from tests.test_chpm_kernel import decision

    assert (await auth_client.patch(PATH, json=update())).status_code == 200
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        value = deepcopy(state.entity_states)
        value[KEY]["actors"] = {"NPC_NEW": decision().model_dump()}
        state.entity_states = value
        await db.commit()
    assert len((await auth_client.get(PATH)).json()["trace"]) == 1
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.role = "user"
        await db.commit()
    assert (await auth_client.get(PATH)).json()["trace"] == []
