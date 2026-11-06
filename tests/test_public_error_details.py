"""Unexpected failures stay actionable without exposing credentials or server paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.api.routes import data, stt_api, users_api
from backend.core.config import settings
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.session_importer import SessionImporter
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_stt import create_dummy_wav

SECRET = "INTERNAL_SENTINEL /srv/private/config.key api_key=credential-sentinel"


async def test_request_id_is_generated_by_the_server(client):
    response = await client.get("/api/health", headers={"X-Request-ID": "untrusted-client-value"})
    assert len(response.headers["x-request-id"]) == 32
    assert response.headers["x-request-id"] != "untrusted-client-value"


def public_failure(response, status=500):
    assert response.status_code == status, response.text
    assert "INTERNAL_SENTINEL" not in response.text
    assert "credential-sentinel" not in response.text and "/srv/private" not in response.text
    assert response.json()["detail"]
    assert len(response.headers["x-request-id"]) == 32


@pytest.fixture(autouse=True)
def temporary_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))


async def test_bio_generation_error_is_private(auth_client, monkeypatch):
    monkeypatch.setattr(
        users_api.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(
            model="mock", aexecute_simple_task=AsyncMock(side_effect=RuntimeError(SECRET))
        ),
    )
    public_failure(await auth_client.post("/api/users/me/bio/generate"))


async def test_avatar_generation_error_is_private(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.t2i_settings = {
            "simple_model_provider": "stable_diffusion",
            "simple_model": "fixture-model",
        }
        await db.commit()
    monkeypatch.setattr(
        users_api.MediaEngine, "generate_image", AsyncMock(side_effect=RuntimeError(SECRET))
    )
    public_failure(await auth_client.post("/api/users/me/profile-image/generate"))


async def test_image_decoder_error_is_private(auth_client, monkeypatch):
    monkeypatch.setattr(data.Image, "open", Mock(side_effect=RuntimeError(SECRET)))
    response = await auth_client.post(
        "/api/data/image", files={"file": ("image.png", b"fixture", "image/png")}
    )
    public_failure(response)


@pytest.mark.parametrize("decode", [True, False])
async def test_speech_errors_are_private(auth_client, monkeypatch, decode):
    if decode:
        monkeypatch.setattr(stt_api, "decode_wav_to_numpy", Mock(side_effect=ValueError(SECRET)))
    else:
        monkeypatch.setattr(stt_api, "get_whisper_model", Mock(side_effect=RuntimeError(SECRET)))
    response = await auth_client.post(
        "/api/stt/transcribe", files={"file": ("audio.wav", create_dummy_wav(), "audio/wav")}
    )
    public_failure(response, 400 if decode else 500)


@pytest.mark.parametrize("kind", ["manifest", "bundle", "adv", "adz", "ads"])
async def test_import_errors_are_private(auth_client, monkeypatch, kind):
    failure = AsyncMock(side_effect=RuntimeError(SECRET))
    if kind in {"manifest", "bundle", "adv"}:
        monkeypatch.setattr(AdventureTemplateImporter, "import_adv_manifest", failure)
    elif kind == "adz":
        monkeypatch.setattr(AdventureTemplateImporter, "import_adz", failure)
    else:
        monkeypatch.setattr(SessionImporter, "import_ads", failure)
    if kind == "manifest":
        response = await auth_client.post("/api/adventures/import", json={"title": "Fixture"})
    elif kind == "bundle":
        response = await auth_client.post(
            "/api/adventures/import/session-bundle", json={"type": "SESSION_BUNDLE"}
        )
    else:
        path = (
            "/api/adventures/sessions/import" if kind == "ads" else f"/api/adventures/import/{kind}"
        )
        response = await auth_client.post(
            path, files={"file": (f"fixture.{kind}", b"{}", "application/octet-stream")}
        )
    public_failure(response)


@pytest.mark.parametrize("operation", ["update-all", "update", "migrate"])
async def test_template_maintenance_errors_are_private(auth_client, monkeypatch, operation):
    from backend.engine import adventure_updates

    name = {
        "update-all": "update_all_adventures",
        "update": "update_single_adventure",
        "migrate": "migrate_single_adventure",
    }[operation]
    monkeypatch.setattr(adventure_updates, name, AsyncMock(side_effect=RuntimeError(SECRET)))
    path = (
        "/api/adventures/templates/update-all"
        if operation == "update-all"
        else f"/api/adventures/templates/fixture/{operation}"
    )
    public_failure(await auth_client.post(path))
