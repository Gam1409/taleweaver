"""Renaming an exported story must not create a different publication identity."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_identity import stable_origin_id
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from tests.conftest import TestSessionLocal


def test_unpublished_identity_survives_renaming_and_supports_unicode_ids():
    template = SimpleNamespace(id="история-日本語", origin_id=None, title="First title")
    identity = stable_origin_id(template)
    assert str(UUID(identity)) == identity
    template.title = "Другое название"
    assert stable_origin_id(template) == identity


def test_same_title_does_not_merge_different_stories():
    first = SimpleNamespace(id="first", origin_id=None, title="The Forest")
    second = SimpleNamespace(id="second", origin_id=None, title="The Forest")
    assert stable_origin_id(first) != stable_origin_id(second)


def test_imported_identity_remains_authoritative():
    template = SimpleNamespace(id="local-copy", origin_id="original-story")
    assert stable_origin_id(template) == "original-story"


@pytest.mark.asyncio
async def test_export_keeps_identity_and_global_script_without_mutating_template(auth_client):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).limit(1))
        template = AdventureTemplate(
            owner_id=user.id,
            title="Дом у реки",
            original_manifest={"init_script": "def greet():\n    return 'Hello'"},
        )
        db.add(template)
        await db.commit()
        first = await AdventureExporter.build_full_manifest(db, template.id)
        template.title = "川辺の家"
        await db.commit()
        renamed = await AdventureExporter.build_full_manifest(db, template.id)
        assert first["adventure"]["origin_id"] == renamed["adventure"]["origin_id"]
        assert first["init_script"] == template.init_script
        assert template.origin_id is None
        assert template not in db.dirty
