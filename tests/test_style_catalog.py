from backend.core.style_catalog import (
    default_image_styles_catalog,
    normalize_image_styles_catalog,
    resolve_style_instruction,
)

LEGACY_ANIME = {
    "id": "shonen-anime",
    "name": "Modern Shonen Anime",
    "description": "Sharp lines, dynamic digital lighting, and high-energy animation style.",
    "instruction": "Modern shonen anime style, crisp line art, dynamic cinematic lighting, vibrant cel-shading, high-octane energy, digital animation aesthetic, sharp focus, vivid special effects.",
    "image_url": "/data/my-anime-preview.png",
}


def test_resolve_style_instruction_uses_default_catalog_when_user_catalog_empty():
    selected = [{"id": "science-fiction"}]
    instruction = resolve_style_instruction(selected, user_catalog=[])
    assert "science fiction" in instruction


def test_resolve_style_instruction_prefers_embedded_instruction():
    selected = [{"id": "science-fiction", "instruction": "custom style prompt"}]
    instruction = resolve_style_instruction(selected, user_catalog=[])
    assert instruction == "custom style prompt"


def test_default_image_styles_catalog_is_copy():
    first = default_image_styles_catalog()
    second = default_image_styles_catalog()
    first[0]["id"] = "mutated"
    assert second[0]["id"] != "mutated"


def test_old_embedded_and_catalog_styles_use_the_current_anime_instruction():
    expected = next(item for item in default_image_styles_catalog() if item["id"] == "shonen-anime")
    assert expected["name"] == "Anime"
    assert "shonen" not in expected["instruction"].lower()
    assert "high-octane" not in expected["instruction"].lower()
    for selection, catalog in (
        ([LEGACY_ANIME], []),
        (["shonen-anime"], [LEGACY_ANIME]),
        (["Modern Shonen Anime"], []),
        (["Anime"], [LEGACY_ANIME]),
    ):
        assert resolve_style_instruction(selection, catalog) == expected["instruction"]
    assert LEGACY_ANIME["name"] == "Modern Shonen Anime"


def test_edited_anime_instructions_are_preserved():
    custom = {
        **LEGACY_ANIME,
        "name": "My anime",
        "instruction": "Watercolor anime with muted colors",
    }
    assert resolve_style_instruction([custom], []) == custom["instruction"]
    assert resolve_style_instruction([custom["id"]], [custom]) == custom["instruction"]


def test_saved_catalog_keeps_ids_and_custom_artwork_when_refreshing_builtin_fields():
    current = normalize_image_styles_catalog([LEGACY_ANIME])[0]
    assert current["name"] == "Anime"
    assert current["id"] == LEGACY_ANIME["id"]
    assert current["image_url"] == LEGACY_ANIME["image_url"]
    assert current["instruction"] == resolve_style_instruction([LEGACY_ANIME], [])
    assert LEGACY_ANIME["name"] == "Modern Shonen Anime"


async def test_old_saved_catalog_is_refreshed_by_settings_api(auth_client):
    from sqlalchemy import select

    from backend.models.user import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.image_styles_catalog = [dict(LEGACY_ANIME)]
        await db.commit()
    response = await auth_client.get("/api/settings")
    assert response.status_code == 200
    style = response.json()["image_styles_catalog"][0]
    assert style["name"] == "Anime"
    assert style["id"] == LEGACY_ANIME["id"]
    assert style["image_url"] == LEGACY_ANIME["image_url"]
    saved = await auth_client.post("/api/settings/image-styles", json={"items": [LEGACY_ANIME]})
    assert saved.status_code == 200
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        assert user.image_styles_catalog[0] == style
