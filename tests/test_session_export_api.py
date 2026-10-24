"""Exercise the real download route, including headers and portable assets."""

import io
import json
import zipfile
from email.message import Message
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.core.config import settings
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from backend.utils.path_security import safe_data_path
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_unicode_session_portraits import seed_localized_session

__all__ = ["portrait_world"]


@pytest.mark.parametrize(
    "title", ["Одинокий путник", "森からの脱出", "رحلة الغابة", "El bosque mágico"]
)
@pytest.mark.parametrize("legacy_id", [True, False])
async def test_localized_session_download(auth_client, portrait_world, title, legacy_id):
    session_id = await seed_localized_session(title, image_url=None, legacy_id=legacy_id)
    folder = Path(safe_data_path("adventures", "sessions", session_id, "visuals"))
    folder.mkdir(parents=True)
    (folder / "портрет.png").write_bytes(b"portrait-fixture")
    async with TestSessionLocal() as db:
        npc = (
            await db.execute(select(WorldEntity).where(WorldEntity.session_id == session_id))
        ).scalar_one()
        npc.image_url = f"/data/adventures/sessions/{session_id}/visuals/портрет.png"
        await db.commit()

    response = await auth_client.get(f"/api/adventures/sessions/{session_id}/export")

    assert response.status_code == 200, response.text[:500]
    assert response.headers["content-type"] == "application/zip"
    header = response.headers["content-disposition"]
    assert header.isascii()
    message = Message()
    message["Content-Disposition"] = header
    assert message.get_filename() == f"session_{session_id}.ads"
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        data = json.loads(bundle.read("session.json"))
        assert data["game_session"]["id"] == session_id
        assert data["game_session"]["adventure_title"] == title
        assert data["world_entities"][0]["name"] == "Вор"
        assert data["world_entities"][0]["image_url"] == "assets/visuals/портрет.png"
        assert bundle.read("assets/visuals/портрет.png") == b"portrait-fixture"

    # A portable save imports under a new ID without changing the original.
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("session.ads", response.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    imported_id = imported.json()["game_id"]
    assert imported_id != session_id and imported_id.isascii()
    async with TestSessionLocal() as db:
        original = await db.get(GameSession, session_id)
        restored = await db.get(GameSession, imported_id)
        state = (
            await db.execute(select(SessionState).where(SessionState.session_id == imported_id))
        ).scalar_one()
        assert original.adventure_title == restored.adventure_title == title
        assert state.in_game_time == 520
        assert state.quests == [{"id": "escape", "status": "active"}]
    assert (
        Path(settings.DATA_DIR)
        / "adventures"
        / "sessions"
        / imported_id
        / "visuals"
        / "портрет.png"
    ).read_bytes() == b"portrait-fixture"


@pytest.mark.parametrize("session_id", ["other-session", "missing-session"])
async def test_export_hides_foreign_and_missing_saves(auth_client, portrait_world, session_id):
    response = await auth_client.get(f"/api/adventures/sessions/{session_id}/export")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found."
