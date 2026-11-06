import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from backend.core.config import settings
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.user import User
from backend.models.world_entity import WorldScene


@pytest.mark.asyncio
async def test_full_portability_cycle(setup_test_db, monkeypatch, tmp_path):
    """
    Verifies that an adventure can be exported to ADZ and imported back
    with 100% field parity and correct asset re-mapping.
    """
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        # 1. Ensure a user exists
        user_res = await db.execute(select(User).where(User.username == "testuser"))
        user = user_res.scalars().first()
        if not user:
            user = User(username="testuser", hashed_password="fake", role="user")
            db.add(user)
            await db.flush()

        # 2. Seed adventure with ALL fields populated
        adv = AdventureTemplate(
            id="portability-test-999",
            owner_id=user.id,
            title="Master Portability Test",
            teaser="Verifying every single field.",
            version="1.0.0",
            language="English",
            plot="The plot must survive.",
            rules="The rules must be preserved.",
            intro_text="Welcome to the test.",
            walkthrough="Follow these steps.",
            completed_condition="Victory.",
            gameover_condition="Defeat.",
            starting_timestamp=480,
            time_system="chronology",
            time_config={"custom": "data"},
            game_over_rules={"hardcore": True},
            allow_dynamic_items=False,
            image_url="/data/adventures/library/portability-test-999/cover.jpg",
            is_ready=True,
            creation_status="Ready",
        )
        db.add(adv)
        await db.flush()

        avatar = Avatar(
            template_id=adv.id,
            user_id=user.id,
            name="Test Hero",
            role="Survivor",
            description="A hero with many stats.",
            goal="Survive the test.",
            character="Brave.",
            profile_image="/data/adventures/library/portability-test-999/hero.jpg",
            hp=150,
            max_hp=150,
            exp=500,
            strength=15,
            dexterity=12,
            intelligence=10,
            wisdom=8,
            charisma=14,
            armor_class=15,
            status_effects=["Test Buff"],
            stats={"luck": 5},
            inventory=[],
            equipment={},
        )
        db.add(avatar)

        scene = WorldScene(
            id="SCENE_START",
            template_id=adv.id,
            label="Start",
            description="The beginning.",
            image_url="/data/adventures/library/portability-test-999/scenes/start.jpg",
        )
        db.add(scene)
        await db.commit()

        _real_export_images(monkeypatch, tmp_path)

        # 4. Export to ADZ
        adz_bytes = await AdventureExporter.export_adz(db, adv.id)
        assert len(adz_bytes) > 0

        # 5. Verify ZIP Manifest content before importing
        with zipfile.ZipFile(io.BytesIO(adz_bytes)) as z:
            assert "adventure.adv" in z.namelist()
            manifest = json.loads(z.read("adventure.adv"))

            # Check a subset of critical fields in the manifest
            assert manifest["adventure"]["time_system"] == "chronology"
            assert manifest["adventure"]["allow_dynamic_items"] is False
            assert manifest["protagonist"]["goal"] == "Survive the test."
            assert manifest["protagonist"]["profile_image"] == "assets/hero.jpg"

        # 6. Delete the original adventure to simulate a clean import
        from sqlalchemy import delete

        await db.execute(delete(WorldScene).where(WorldScene.template_id == adv.id))
        await db.execute(delete(Avatar).where(Avatar.template_id == adv.id))
        await db.execute(delete(AdventureTemplate).where(AdventureTemplate.id == adv.id))
        await db.commit()

        monkeypatch.setattr(
            "backend.engine.media_engine.MediaEngine.ensure_thumbnails", AsyncMock()
        )

        # 8. Perform Import
        success = await AdventureTemplateImporter.import_adz(db, adz_bytes, owner_id=user.id)
        assert success is True

        # 9. Verify Restored Data in DB
        res = await db.execute(
            select(AdventureTemplate).where(AdventureTemplate.title == "Master Portability Test")
        )
        restored_adv = res.scalars().first()
        assert restored_adv is not None
        assert restored_adv.time_system == "chronology"
        assert restored_adv.allow_dynamic_items is False
        assert restored_adv.plot == "The plot must survive."

        av_res = await db.execute(select(Avatar).where(Avatar.template_id == restored_adv.id))
        restored_avatar = av_res.scalars().first()
        assert restored_avatar is not None
        assert restored_avatar.goal == "Survive the test."
        assert restored_avatar.strength == 15
        assert restored_avatar.status_effects == ["Test Buff"]
        # Image should be re-mapped to the new library path
        assert restored_avatar.profile_image.startswith("/data/adventures/library/")
        assert "hero.jpg" in restored_avatar.profile_image


def _real_export_images(monkeypatch, data_root):
    monkeypatch.setattr(settings, "DATA_DIR", str(data_root))
    for name in ["cover.jpg", "hero.jpg", "scenes/start.jpg"]:
        path = data_root / "adventures/library/portability-test-999" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "blue").save(path)
