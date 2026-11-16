"""Template operations must never adopt characters belonging to saved games."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from backend.api.routes.adventures.assets import suggest_prompt
from backend.api.routes.adventures.editing.common import _get_template_avatar
from backend.api.routes.adventures.legacy_session_mutations import reset_sessions
from backend.api.routes.adventures.session_start_avatar import resolve_start_avatar
from backend.api.routes.adventures.template_reset import _restore_protagonist
from backend.api.routes.adventures.visual_upload import resolve_visual_upload_target
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.gameplay.session_sheet import _sheet_profile_image
from backend.engine.manifest_apply.avatar import persist_avatar
from backend.engine.manifest_apply.context import ApplyContext
from backend.engine.template_avatar import avatar_from_manifest
from backend.engine.visual_regeneration import _target
from backend.engine.world_generation_persistence import load_cover_source_assets
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

pytestmark = pytest.mark.asyncio

AUTHORED = {
    "name": "Archive keeper",
    "role": "Navigator",
    "description": "An authored protagonist.",
    "goal": "Find the observatory.",
    "character": "Patient and observant.",
    "gender": "nonbinary",
    "age_years": 41,
    "visual_profile": {"identity": {"age_years": 41}},
    "hp": 0,
    "max_hp": 135,
    "stamina": 61,
    "max_stamina": 120,
    "mana": 0,
    "max_mana": 99,
    "exp": 17,
    "strength": 12,
    "dexterity": 13,
    "intelligence": 14,
    "wisdom": 15,
    "charisma": 16,
    "armor_class": 11,
    "stats": {"authored_marker": "public", "special_actions": []},
    "status_effects": ["focused"],
    "inventory": [{"id": "MAP", "name": "Authored map"}],
    "equipment": {"MainHand": {"id": "COMPASS", "name": "Authored compass"}},
}


def _manifest_protagonist() -> dict:
    protagonist = deepcopy(AUTHORED)
    protagonist["starting_inventory"] = protagonist.pop("inventory")
    protagonist["starting_equipment"] = protagonist.pop("equipment")
    return protagonist


@pytest_asyncio.fixture
async def avatar_world(auth_client, db_session):
    """Seed both a foreign character and the template owner's saved character."""
    owner = await db_session.scalar(select(User).where(User.username == "test_user"))
    other = User(id="other-player", username="other-player", hashed_password="synthetic")
    template = AdventureTemplate(
        id="avatar-isolation",
        owner_id=owner.id,
        title="Avatar isolation",
        is_ready=True,
        original_manifest={"protagonist": _manifest_protagonist()},
    )
    db_session.add_all([other, template])
    await db_session.flush()
    characters = []
    for index, user in enumerate((other, owner)):
        character = Avatar(
            id=f"saved-avatar-{index}",
            user_id=user.id,
            template_id=template.id,
            name=f"Saved character {index}",
            description=f"PRIVATE_SAVED_DESCRIPTION_{index}",
            stats={"private_marker": index},
            inventory=[{"id": "PRIVATE_NOTE", "name": f"Private note {index}"}],
            equipment={"MainHand": {"id": "PRIVATE_ITEM"}},
            created_at=datetime(2020, 1, index + 1),
        )
        db_session.add(character)
        await db_session.flush()
        db_session.add(
            GameSession(
                id=f"saved-game-{index}",
                user_id=user.id,
                template_id=template.id,
                avatar_id=character.id,
            )
        )
        characters.append(character)
    await db_session.commit()
    return SimpleNamespace(
        client=auth_client,
        db=db_session,
        owner=owner,
        template=template,
        characters=characters,
    )


async def _add_blueprint(world) -> Avatar:
    """A genuine blueprint wins even when saved characters were created earlier."""
    avatar = Avatar(
        id="genuine-blueprint",
        user_id=world.owner.id,
        template_id=world.template.id,
        created_at=datetime(2025, 1, 1),
        **deepcopy(AUTHORED),
    )
    avatar.description = "The edited blueprint takes priority over the manifest."
    world.db.add(avatar)
    await world.db.commit()
    return avatar


def _assert_authored(values: dict, *, blueprint: bool, exported: bool = False) -> None:
    expected = deepcopy(AUTHORED)
    if blueprint:
        expected["description"] = "The edited blueprint takes priority over the manifest."
    if exported:
        expected["inventory"] = ["MAP"]
        expected["equipment"] = {"MainHand": "COMPASS"}
    for field, value in expected.items():
        if field == "equipment":
            assert values[field]["MainHand"] == value["MainHand"]
        else:
            assert values[field] == value, field


def _avatar_values(avatar: Avatar) -> dict:
    return {field: getattr(avatar, field) for field in AUTHORED}


@pytest.mark.parametrize("blueprint", [False, True])
@pytest.mark.parametrize("shared", [False, True])
async def test_duplicate_copies_only_the_authored_protagonist(avatar_world, blueprint, shared):
    world = avatar_world
    if blueprint:
        await _add_blueprint(world)
    if shared:
        world.template.owner_id = None
        await world.db.commit()

    response = await world.client.post(f"/api/adventures/{world.template.id}/duplicate")
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    avatars = list(await world.db.scalars(select(Avatar).where(Avatar.template_id == clone_id)))
    assert len(avatars) == 1
    assert avatars[0].user_id == world.owner.id
    _assert_authored(_avatar_values(avatars[0]), blueprint=blueprint)

    editor = await world.client.get(f"/api/adventures/{clone_id}/editor/assets")
    assert editor.status_code == 200, editor.text
    _assert_authored(editor.json()["protagonist"], blueprint=blueprint)


@pytest.mark.parametrize("blueprint", [False, True])
async def test_start_selects_blueprint_or_manifest_without_saved_state(avatar_world, blueprint):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    selected = await _get_template_avatar(world.db, world.template.id)
    assert selected is original

    avatar = await resolve_start_avatar(world.db, world.template.id, world.owner, world.template)
    assert avatar not in world.characters
    _assert_authored(_avatar_values(avatar), blueprint=blueprint)
    avatar.inventory[0]["name"] = "Independent new session"
    avatar.equipment["MainHand"]["name"] = "Independent equipment"
    assert (
        world.template.original_manifest["protagonist"]["starting_inventory"]
        == AUTHORED["inventory"]
    )
    if original:
        assert original.inventory == AUTHORED["inventory"]
        assert original.equipment == AUTHORED["equipment"]


@pytest.mark.parametrize("blueprint", [False, True])
async def test_export_uses_authored_protagonist_when_owner_has_saved_game(avatar_world, blueprint):
    world = avatar_world
    if blueprint:
        await _add_blueprint(world)
    manifest = await AdventureExporter.build_full_manifest(world.db, world.template.id)
    protagonist = dict(manifest["protagonist"])
    protagonist["inventory"] = protagonist.pop("starting_inventory")
    protagonist["equipment"] = protagonist.pop("starting_equipment")
    _assert_authored(protagonist, blueprint=blueprint, exported=True)


async def test_editor_restores_manifest_instead_of_a_saved_character(avatar_world):
    response = await avatar_world.client.get(
        f"/api/adventures/{avatar_world.template.id}/editor/assets"
    )
    assert response.status_code == 200, response.text
    protagonist = response.json()["protagonist"]
    assert protagonist["id"] not in {avatar.id for avatar in avatar_world.characters}
    _assert_authored(protagonist, blueprint=False)


@pytest.mark.parametrize("blueprint", [False, True])
async def test_manifest_update_preserves_saved_characters(avatar_world, blueprint, monkeypatch):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    snapshots = [_avatar_values(avatar) for avatar in world.characters]
    monkeypatch.setattr(
        "backend.engine.manifest_apply.avatar._portrait", AsyncMock(return_value=None)
    )
    ctx = ApplyContext(world.db, world.template.id, {}, world.owner, world.template)
    avatar, _ = await persist_avatar(ctx, {"name": "Updated authored protagonist"})
    await world.db.commit()

    assert avatar not in world.characters
    if original:
        assert avatar is original
    assert avatar.name == "Updated authored protagonist"
    for saved, snapshot in zip(world.characters, snapshots, strict=True):
        await world.db.refresh(saved)
        assert _avatar_values(saved) == snapshot


@pytest.mark.parametrize("blueprint", [False, True])
async def test_visual_and_reset_targets_exclude_saved_characters(avatar_world, blueprint):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    snapshots = [_avatar_values(avatar) for avatar in world.characters]
    payload = SimpleNamespace(target_type="protagonist", target_id="")
    if original:
        assert (await _target(world.db, world.template, payload))[0] is original
        assert (
            await resolve_visual_upload_target(world.db, world.template, "protagonist", "")
        ) is original
    else:
        with pytest.raises(HTTPException, match="404"):
            await _target(world.db, world.template, payload)
        with pytest.raises(HTTPException, match="404"):
            await resolve_visual_upload_target(world.db, world.template, "protagonist", "")

    await _restore_protagonist(world.db, world.template.id, {"name": "Reset authored name"})
    await world.db.commit()
    if original:
        assert original.name == "Reset authored name"
    for saved, snapshot in zip(world.characters, snapshots, strict=True):
        await world.db.refresh(saved)
        assert _avatar_values(saved) == snapshot


@pytest.mark.parametrize("blueprint", [False, True])
async def test_reset_does_not_promote_retained_session_characters(avatar_world, blueprint):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    await reset_sessions(world.db, world.template.id, world.owner.id)

    assert list(await world.db.scalars(select(GameSession))) == []
    for saved in world.characters:
        await world.db.refresh(saved)
        assert saved.template_id is None
    assert await _get_template_avatar(world.db, world.template.id) is original


async def test_session_reference_protects_avatar_even_with_detached_template(avatar_world):
    world = avatar_world
    sessions = list(await world.db.scalars(select(GameSession)))
    for session in sessions:
        session.template_id = None
    await world.db.commit()
    assert await _get_template_avatar(world.db, world.template.id) is None


@pytest.mark.parametrize("manifest", [None, {}, {"protagonist": {}}])
async def test_legacy_default_fallbacks_exclude_saved_state(avatar_world, manifest):
    world = avatar_world
    world.template.original_manifest = manifest
    await world.db.commit()
    avatar = await resolve_start_avatar(world.db, world.template.id, world.owner, world.template)
    assert avatar.name == "Hero"
    assert avatar.inventory == []
    assert avatar.stats == {}
    exported = await AdventureExporter.build_full_manifest(world.db, world.template.id)
    assert exported["protagonist"]["name"] == "Hero"
    assert exported["protagonist"]["starting_inventory"] == []
    preview = await world.client.get(f"/api/adventures/{world.template.id}/export/session")
    assert preview.status_code == 200, preview.text
    assert preview.json()["avatar"]["name"] == "Hero"
    copied = await world.client.post(f"/api/adventures/{world.template.id}/duplicate")
    assert copied.status_code == 201, copied.text
    avatars = list(
        await world.db.scalars(select(Avatar).where(Avatar.template_id == copied.json()["id"]))
    )
    assert len(avatars) == 1
    assert avatars[0].name == "Hero"
    assert avatars[0].stats == {}


@pytest.mark.parametrize("blueprint", [False, True])
async def test_visual_consumers_never_reuse_saved_character_data(
    avatar_world, blueprint, monkeypatch
):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    for index, saved in enumerate(world.characters):
        saved.profile_image = f"/data/private-saved-{index}.png"
    if original:
        original.profile_image = "/data/authored.png"
    await world.db.commit()
    mock_prompt = AsyncMock(return_value="Authored image prompt")
    monkeypatch.setattr("backend.engine.preset_prompt_suggestion.suggest_image_prompt", mock_prompt)
    prompt = await suggest_prompt(
        world.template.id,
        SimpleNamespace(target_type="protagonist", target_id=""),
        world.db,
        world.owner,
    )
    if original:
        assert prompt.suggested_prompt == "Authored image prompt"
        assert mock_prompt.call_args.args[-2:] == (original.name, original.description)
    else:
        assert prompt.suggested_prompt == ""
        mock_prompt.assert_not_awaited()
    source = await load_cover_source_assets(world.db, world.template.id, True)
    assert source["protagonist"]["name"] == (original.name if original else "")
    monkeypatch.setattr(
        "backend.engine.gameplay.world.AdventureLogic.resolve_existing_data_asset_url",
        lambda candidate: candidate,
    )
    state = SessionState(
        session_id="saved-game-1",
        avatar_id=world.characters[1].id,
        template_id=world.template.id,
        entity_states={},
    )
    current = Avatar(user_id=world.owner.id, name="Current character")
    image = await _sheet_profile_image(world.db, current, state, {})
    assert image == (original.profile_image if original else None)


@pytest.mark.parametrize("blueprint", [False, True])
async def test_delete_removes_last_reference_character_without_promoting_another(
    avatar_world, blueprint
):
    world = avatar_world
    original = await _add_blueprint(world) if blueprint else None
    response = await world.client.delete("/api/adventures/sessions/saved-game-1")
    assert response.status_code == 200, response.text
    assert await world.db.get(Avatar, "saved-avatar-1", populate_existing=True) is None
    assert await _get_template_avatar(world.db, world.template.id) is original


@pytest.mark.parametrize("declared", [False, True])
async def test_manifest_starting_items_preserve_explicit_clear_and_legacy_aliases(declared):
    protagonist = {
        "inventory": deepcopy(AUTHORED["inventory"]),
        "equipment": deepcopy(AUTHORED["equipment"]),
    }
    if declared:
        protagonist.update(starting_inventory=[], starting_equipment={})
    avatar = avatar_from_manifest(
        {"protagonist": protagonist}, template_id="template", user_id="owner"
    )
    assert avatar.inventory == ([] if declared else AUTHORED["inventory"])
    assert avatar.equipment["MainHand"] == (None if declared else AUTHORED["equipment"]["MainHand"])
