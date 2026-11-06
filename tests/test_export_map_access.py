"""Private exports and map operations authorize the entire requested scope."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.core.config import settings
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldExit
from backend.models.world_map import WorldMap
from tests.conftest import TestSessionLocal
from tests.test_session_state_access import access_world

__all__ = ["access_world"]


@pytest.fixture
async def private_world(access_world, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    owner_id, other_id, _ = access_world
    async with TestSessionLocal() as db:
        db.add(AdventureTemplate(id="PRIVATE", owner_id=other_id, title="Private", is_ready=False))
        await db.flush()
        for model, key in [
            (GameSession, "session-other"),
            (SessionState, "state-other"),
            (Avatar, "hero-other"),
        ]:
            (await db.get(model, key)).template_id = "PRIVATE"
        own = await db.get(AdventureTemplate, "SHARED")
        own.original_manifest = {"format": "TaleWeaver", "version": "1.3", "scenes": []}
        db.add(
            WorldMap(
                template_id="PRIVATE",
                session_id="session-other",
                nodes={"SECRET": {"id": "SECRET"}},
                edges=[],
                current_scene_id="SECRET",
            )
        )
        await db.commit()
    return owner_id, other_id


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("format_name", ["adv", "adz", "session", "manifest"])
async def test_foreign_exports_fail_before_building_or_reading_files(
    auth_client, private_world, monkeypatch, role, format_name
):
    owner_id, _ = private_world
    async with TestSessionLocal() as db:
        (await db.get(User, owner_id)).role = role
        await db.commit()
    build = AsyncMock(side_effect=AssertionError("Unauthorized export must not build a manifest"))
    archive = AsyncMock(side_effect=AssertionError("Unauthorized export must not read files"))
    monkeypatch.setattr(AdventureExporter, "build_full_manifest", build)
    monkeypatch.setattr(AdventureExporter, "export_adz", archive)
    response = await auth_client.get(f"/api/adventures/PRIVATE/export/{format_name}")
    assert response.status_code == 404, response.text
    build.assert_not_awaited()
    archive.assert_not_awaited()


@pytest.mark.parametrize("format_name", ["adv", "adz", "session", "manifest"])
async def test_owner_export_still_works_and_unknown_template_is_hidden(
    auth_client, private_world, format_name
):
    assert (
        await auth_client.get(f"/api/adventures/SHARED/export/{format_name}")
    ).status_code == 200
    assert (
        await auth_client.get(f"/api/adventures/MISSING/export/{format_name}")
    ).status_code == 404


async def test_template_export_never_chooses_another_players_avatar(auth_client, private_world):
    async with TestSessionLocal() as db:
        other = await db.get(Avatar, "hero-other")
        other.template_id = "SHARED"
        other.created_at = (await db.get(Avatar, "hero-own")).created_at
        await db.commit()
    for format_name in ["session", "adv"]:
        response = await auth_client.get(f"/api/adventures/SHARED/export/{format_name}")
        assert response.status_code == 200, response.text
        assert "hero-other" not in response.text
        payload = response.json()
        assert (payload.get("avatar") or payload.get("protagonist"))["name"] == "own"


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("operation", ["read", "visit", "exit"])
async def test_map_rejects_cross_template_session_before_creation(
    auth_client, private_world, role, operation
):
    owner_id, _ = private_world
    async with TestSessionLocal() as db:
        (await db.get(User, owner_id)).role = role
        await db.delete(await db.scalar(select(WorldMap)))
        await db.commit()
    path = "/api/adventures/SHARED/map?session_id=session-other"
    if operation == "read":
        response = await auth_client.get(path)
    else:
        body = (
            {"scene_id": "FORGED"} if operation == "visit" else {"from_scene": "A", "to_scene": "B"}
        )
        response = await auth_client.post(path.replace("/map?", f"/map/{operation}?"), json=body)
    assert response.status_code == 404, response.text
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(WorldMap)) == 0


async def test_map_requires_session_ownership_but_keeps_explicit_admin_access(
    auth_client, private_world
):
    owner_id, _ = private_world
    path = "/api/adventures/PRIVATE/map?session_id=session-other"
    assert (await auth_client.get(path)).status_code == 404
    async with TestSessionLocal() as db:
        (await db.get(User, owner_id)).role = "admin"
        await db.commit()
    assert (await auth_client.get(path)).status_code == 200


async def test_player_can_read_their_session_of_another_authors_template(
    auth_client, private_world
):
    async with TestSessionLocal() as db:
        (await db.get(GameSession, "session-own")).template_id = "PRIVATE"
        await db.commit()
    response = await auth_client.get("/api/adventures/PRIVATE/map?session_id=session-own")
    assert response.status_code == 200, response.text


async def test_map_writes_share_turn_lease_and_reads_remain_available(auth_client, private_world):
    with session_write_lease("session-own"):
        response = await auth_client.post(
            "/api/adventures/SHARED/map/visit?session_id=session-own", json={"scene_id": "START"}
        )
        assert response.status_code == 409, response.text
        assert (
            await auth_client.get("/api/adventures/SHARED/map?session_id=session-own")
        ).status_code == 200


async def test_template_map_does_not_import_other_sessions_exits(auth_client, private_world):
    async with TestSessionLocal() as db:
        db.add(
            WorldMap(
                template_id="SHARED",
                session_id=None,
                nodes={"START": {"id": "START"}},
                edges=[],
                current_scene_id="START",
            )
        )
        db.add(
            WorldExit(
                id="foreign-exit",
                session_id="session-other",
                template_id="SHARED",
                from_scene_id="START",
                to_scene_id="SECRET",
                label="Private exit",
            )
        )
        await db.commit()
    response = await auth_client.get("/api/adventures/SHARED/map")
    assert response.status_code == 200
    assert "SECRET" not in response.text and "Private exit" not in response.text
