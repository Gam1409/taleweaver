"""Session visuals may copy authorized images, never private files or foreign assets."""

import io
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image

from backend.api.routes.adventures.session_materializer import (
    copy_data_asset_to_session,
    materialize_initial_session_from_template,
)
from backend.core.auth import create_user_access_token
from backend.core.config import settings
from backend.engine import export_asset_policy
from backend.main import app
from backend.models import Avatar, GameSession, SessionState, User, WorldScene
from backend.models.adventure_template import AdventureTemplate
from backend.utils import media_access
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    return stream.getvalue()


def write_file(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@dataclass
class AssetFixture:
    root: Path
    headers: dict[str, str]


@pytest_asyncio.fixture
async def assets(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media_access, "AsyncSessionLocal", TestSessionLocal)
    media_route = next(route for route in app.routes if getattr(route, "path", None) == "/data")
    monkeypatch.setattr(media_route.app, "directory", str(tmp_path))
    monkeypatch.setattr(media_route.app, "all_directories", [str(tmp_path)])
    async with TestSessionLocal() as db:
        owner = User(
            id="asset-owner",
            username="asset-owner",
            hashed_password="unused",
            has_imported_defaults=True,
        )
        other = User(
            id="asset-other",
            username="asset-other",
            hashed_password="unused",
            has_imported_defaults=True,
        )
        db.add_all([owner, other])
        await db.flush()
        db.add_all(
            [
                AdventureTemplate(id="OWN", title="Own template", owner_id=owner.id),
                AdventureTemplate(id="OTHER", title="Other template", owner_id=other.id),
                AdventureTemplate(id="SHARED", title="Shared template", owner_id=None),
                Avatar(id="source-avatar", user_id=owner.id, template_id="OWN", name="Hero"),
                Avatar(id="other-avatar", user_id=other.id, name="Other hero"),
            ]
        )
        await db.flush()
        db.add_all(
            [
                GameSession(
                    id="source-session",
                    user_id=owner.id,
                    template_id="OWN",
                    avatar_id="source-avatar",
                    adventure_title="Asset fixture",
                ),
                GameSession(id="other-session", user_id=other.id, avatar_id="other-avatar"),
                WorldScene(id="ROOM", template_id="OWN", label="Room", description="A room."),
                WorldScene(
                    id="ROOM", session_id="source-session", label="Room", description="A room."
                ),
            ]
        )
        await db.flush()
        db.add(
            SessionState(
                session_id="source-session",
                user_id=owner.id,
                avatar_id="source-avatar",
                current_scene_id="ROOM",
            )
        )
        await db.commit()
        headers = {"Authorization": f"Bearer {create_user_access_token(owner)}"}
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
    return AssetFixture(tmp_path, headers)


async def copied_item(client, assets, url):
    response = await client.patch(
        "/api/avatars/source-avatar",
        headers=assets.headers,
        json={"inventory": [{"id": "TOKEN", "name": "Token", "image_url": url}]},
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        "/api/adventures/sessions/source-session/copy", headers=assets.headers
    )
    assert response.status_code == 201, response.text
    copied = response.json()
    avatar = await client.get("/api/avatars/" + copied["avatar_id"], headers=assets.headers)
    return copied["game_id"], avatar.json()["inventory"][0]["image_url"]


@pytest.mark.parametrize(
    "relative,valid_image",
    [
        ("taleweaver.db", False),
        ("logs/private.json", False),
        ("logs/private.png", False),
        ("adventures/sessions/source-session/renamed.png", False),
        ("adventures/library/OWN/renamed.png", False),
        ("adventures/sessions/other-session/image.png", True),
        ("adventures/library/OTHER/image.png", True),
    ],
)
async def test_copy_does_not_publish_private_or_invalid_sources(
    client, assets, relative, valid_image
):
    data = image_bytes() if valid_image else b"neutral private fixture; not an image"
    write_file(assets.root, relative, data)
    url = "/data/" + relative
    _, copied_url = await copied_item(client, assets, url)
    assert copied_url == url


@pytest.mark.parametrize(
    "relative",
    [
        "adventures/sessions/source-session/image.png",
        "adventures/library/OWN/image.png",
        "adventures/library/SHARED/image.png",
        "adventures/OWN/image.png",
        "catalog/styles/image.png",
        "characters/image.png",
        "root-image.png",
    ],
)
async def test_authorized_images_get_independent_session_copies(client, assets, relative):
    data = image_bytes()
    source = write_file(assets.root, relative, data)
    game_id, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert copied_url.startswith(f"/data/adventures/sessions/{game_id}/visuals/items/")
    source.unlink()
    response = await client.get(copied_url)
    assert response.status_code == 200
    assert response.content == data


async def test_missing_source_does_not_fall_back_to_another_users_image(client, assets):
    write_file(assets.root, "adventures/sessions/other-session/same.png", image_bytes())
    url = "/data/adventures/library/OWN/missing/same.png"
    _, copied_url = await copied_item(client, assets, url)
    assert copied_url == url


async def test_legacy_missing_source_can_find_an_authorized_image(client, assets):
    data = image_bytes()
    write_file(assets.root, "adventures/library/OWN/recovered/same.png", data)
    _, copied_url = await copied_item(
        client, assets, "/data/adventures/library/OWN/missing/same.png"
    )
    response = await client.get(copied_url)
    assert response.status_code == 200
    assert response.content == data


async def test_source_symlink_cannot_cross_to_another_private_scope(client, assets):
    target = write_file(assets.root, "adventures/sessions/other-session/image.png", image_bytes())
    link = assets.root / "adventures/library/OWN/link.png"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    url = "/data/adventures/library/OWN/link.png"
    _, copied_url = await copied_item(client, assets, url)
    assert copied_url == url


async def test_admin_can_copy_a_readable_image_from_another_session(client, assets):
    data = image_bytes()
    relative = "adventures/sessions/other-session/image.png"
    write_file(assets.root, relative, data)
    async with TestSessionLocal() as db:
        user = await db.get(User, "asset-owner")
        user.role = "admin"
        await db.commit()
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert copied_url != "/data/" + relative
    response = await client.get(copied_url)
    assert response.status_code == 200
    assert response.content == data


async def test_generated_session_does_not_publish_private_cover(client, assets):
    write_file(assets.root, "logs/private.json", b"neutral private fixture")
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "OWN")
        template.image_url = "/data/logs/private.json"
        await db.flush()
        await materialize_initial_session_from_template(db, "OWN", "source-session")
        await db.commit()
        session = await db.get(GameSession, "source-session")
        assert session.adventure_image_url == template.image_url


async def test_generated_session_still_copies_its_template_cover(client, assets):
    data = image_bytes()
    write_file(assets.root, "adventures/library/OWN/cover.png", data)
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "OWN")
        template.image_url = "/data/adventures/library/OWN/cover.png"
        await db.flush()
        await materialize_initial_session_from_template(db, "OWN", "source-session")
        await db.commit()
        session = await db.get(GameSession, "source-session")
        assert session.adventure_image_url != template.image_url
        response = await client.get(session.adventure_image_url)
        assert response.status_code == 200
        assert response.content == data


async def test_materializer_copy_without_a_scope_cannot_read_internal_files(assets):
    write_file(assets.root, "logs/private.json", b"neutral private fixture")
    url = "/data/logs/private.json"
    assert copy_data_asset_to_session("target-session", "cover", url, {}) == url


async def test_thumbnail_is_derived_from_the_checked_image(client, assets):
    relative = "adventures/library/OWN/image.png"
    write_file(assets.root, relative, image_bytes())
    private = b"neutral private sibling fixture"
    write_file(assets.root, "adventures/library/OWN/image_thumb.png", private)
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    thumbnail_url = copied_url.removesuffix(".png") + "_thumb.png"
    response = await client.get(thumbnail_url)
    assert response.status_code == 200
    assert response.content != private
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        thumbnail.verify()


async def test_authorized_svg_remains_portable(client, assets):
    relative = "adventures/library/OWN/icon.svg"
    data = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'
    write_file(assets.root, relative, data)
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert copied_url != "/data/" + relative
    response = await client.get(copied_url)
    assert response.status_code == 200
    assert response.content == data


async def test_svg_external_entities_are_not_copied(client, assets):
    relative = "adventures/library/OWN/icon.svg"
    data = b'<!DOCTYPE svg [<!ENTITY e SYSTEM "file:///not-read">]><svg>&e;</svg>'
    write_file(assets.root, relative, data)
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert copied_url == "/data/" + relative


@pytest.mark.parametrize("budget_delta", [-1, 0])
async def test_copy_respects_the_shared_image_byte_budget(
    client, assets, monkeypatch, budget_delta
):
    relative = "adventures/library/OWN/image.png"
    data = image_bytes()
    write_file(assets.root, relative, data)
    monkeypatch.setattr(export_asset_policy, "MAX_ENTRY_BYTES", len(data) + budget_delta)
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert (copied_url == "/data/" + relative) is (budget_delta < 0)


async def test_oversized_pixel_dimensions_do_not_break_session_copy(client, assets, monkeypatch):
    relative = "adventures/library/OWN/image.png"
    write_file(assets.root, relative, image_bytes())
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    _, copied_url = await copied_item(client, assets, "/data/" + relative)
    assert copied_url == "/data/" + relative
