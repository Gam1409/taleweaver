"""Explicit character facts survive editing and reach narration and visual consumers."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.adventures.editing.schemas import EntityUpdateRequest
from backend.engine.character_identity import (
    describe_character,
    identity_facts,
    identity_profile,
    update_identity,
)
from backend.engine.clothing.visuals import character_visuals
from backend.engine.memory_manager import MemoryManager
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from backend.schemas.character_identity import CharacterIdentityFields
from tests.conftest import TestSessionLocal
from tests.test_editor_entity_update import _seed


def test_unknown_identity_does_not_invent_facts_or_enable_managed_clothing():
    actor = Avatar(name="Hero", description="A traveler.", age_years=0)
    assert identity_facts(actor) == {"age_years": 0}
    assert character_visuals(actor, []) is None
    assert describe_character(actor) == "A traveler.; age_years: 0"
    assert identity_facts({}) == {}


@pytest.mark.parametrize("age", [-1, 100001, True, 18.5, "20"])
def test_invalid_ages_rejected(age):
    with pytest.raises(ValidationError):
        CharacterIdentityFields(age_years=age)


def test_clear_legacy_age_and_preserve_unspecified_fields():
    actor = SimpleNamespace(
        gender="female",
        age_years=None,
        visual_profile={"appearance": {"age_years": 25, "hair": "black"}, "worn": []},
    )
    assert identity_facts(actor)["age_years"] == 25
    update_identity(actor, EntityUpdateRequest(target_type="npc", target_id="NPC", age_years=None))
    assert identity_facts(actor) == {"gender": "female"}
    assert actor.visual_profile["appearance"]["hair"] == "black"
    assert actor.visual_profile["worn"] == []


def test_card_age_overrides_legacy_profile_without_mutating_it():
    raw = {"appearance": {"age_years": 40}, "worn": []}
    actor = Avatar(name="Hero", gender="female", age_years=16, visual_profile=raw)
    projected = character_visuals(actor, [], detailed=True)
    assert "age_years: 16" in projected["appearance"]
    assert "gender: female" in projected["appearance"]
    assert "40" not in projected["appearance"]
    assert projected["clothing_detail_limited"] is True
    assert identity_profile(actor, raw)["appearance"]["age_years"] == 16
    assert raw["appearance"]["age_years"] == 40


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["npc", "protagonist"])
async def test_editor_identity_save_omit_clear(auth_client, setup_test_db, kind):
    template_id = await _seed()
    model = Avatar if kind == "protagonist" else WorldEntity
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(model).where(model.template_id == template_id))
        target_id = actor.id
    url = f"/api/adventures/{template_id}/editor/entity"
    base = {"target_type": kind, "target_id": target_id}
    response = await auth_client.patch(url, json={**base, "gender": " female ", "age_years": 26})
    assert response.status_code == 200, response.text
    response = await auth_client.patch(url, json={**base, "description": "Updated bio."})
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(model).where(model.template_id == template_id))
        assert (actor.gender, actor.age_years) == ("female", 26)
        assert actor.visual_profile is None
        if kind == "protagonist":
            sheet = MemoryManager.build_character_sheet(actor)
            assert sheet["gender"] == "female"
            assert sheet["age_years"] == 26
    response = await auth_client.patch(url, json={**base, "gender": None, "age_years": None})
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(model).where(model.template_id == template_id))
        assert actor.gender is None and actor.age_years is None


def test_identity_migration_preserves_existing_characters():
    import importlib.util

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "identity_migration", "alembic/versions/b7a8c9d0e101_character_card_identity.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    tables = [
        sa.Table(
            name,
            metadata,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("name", sa.String),
        )
        for name in ("avatars", "world_entities")
    ]
    with engine.begin() as connection:
        metadata.create_all(connection)
        for table in tables:
            connection.execute(table.insert().values(id="legacy", name="Existing"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            for table in tables:
                upgraded = sa.Table(table.name, sa.MetaData(), autoload_with=connection)
                row = connection.execute(
                    sa.select(upgraded.c.name, upgraded.c.gender, upgraded.c.age_years)
                ).one()
                assert tuple(row) == ("Existing", None, None)
            migration.downgrade()
        for table in tables:
            assert connection.execute(sa.select(table.c.name)).scalar() == "Existing"
    engine.dispose()
