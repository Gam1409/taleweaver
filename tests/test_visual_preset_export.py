"""An adventure's global/saved image source must survive both export formats."""

import io
import json
import zipfile

import pytest
from sqlalchemy import select

from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.story_visual_presets import story_t2i
from backend.engine.world_generation_persistence import persist_generated_narrative
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.user import User
from backend.models.world_entity import WorldScene
from tests.test_comfyui import workflow

__all__ = ["workflow"]

pytestmark = pytest.mark.asyncio
SELECTION = {"background": "previous-server-preset", "advanced": "previous-server-preset"}


async def seed(db, workflow):
    user = await db.scalar(select(User))
    user.t2i_settings = {
        "comfyui_presets": {
            "previous-server-preset": {"name": "Original preset", "generate": workflow}
        }
    }
    adventure = AdventureTemplate(
        id="visual-source-export",
        title="Visual source export",
        owner_id=user.id,
        original_manifest={"visual_presets": SELECTION},
    )
    db.add(adventure)
    await db.flush()
    db.add(
        Avatar(
            template_id=adventure.id,
            user_id=user.id,
            name="Alex",
            role="Explorer",
            description="An explorer.",
        )
    )
    db.add(
        WorldScene(template_id=adventure.id, id="ROOM", label="Room", description="A quiet room.")
    )
    await db.commit()
    return user, adventure


@pytest.mark.parametrize("source", ["current", "saved", None], ids=["current", "saved", "legacy"])
@pytest.mark.parametrize("kind", ["adv", "adz"])
async def test_image_source_survives_export_and_import(
    db_session, auth_client, workflow, source, kind
):
    user, adventure = await seed(db_session, workflow)
    if source is not None:
        adventure.original_manifest = {
            **adventure.original_manifest,
            "visual_preset_source": source,
        }
        await db_session.commit()
    if kind == "adz":
        archive = await AdventureExporter.export_adz(db_session, adventure.id)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            manifest = json.loads(bundle.read("adventure.adv"))
    else:
        manifest = await AdventureExporter.build_full_manifest(db_session, adventure.id)
    assert manifest["visual_preset_source"] == (source or "saved")
    assert manifest["visual_presets"] == SELECTION
    manifest["adventure"]["title"] = "Imported image source"
    assert await AdventureTemplateImporter.import_adv_manifest(db_session, manifest, user.id)
    imported = await db_session.scalar(
        select(AdventureTemplate).where(AdventureTemplate.title == "Imported image source")
    )
    assert imported.original_manifest["visual_preset_source"] == (source or "saved")
    assert imported.original_manifest["visual_presets"] == SELECTION
    if source == "current":
        # An old machine's preset IDs must not override the new global configuration.
        settings = story_t2i({"comfyui_presets": {}, "advanced_model": "current-model"}, imported)
        assert settings["advanced_model"] == "current-model"
    else:
        with pytest.raises(ValueError, match="unavailable"):
            story_t2i({"comfyui_presets": {}}, imported)


async def test_current_source_does_not_block_generated_manifest_persistence(
    db_session, auth_client
):
    user = await db_session.scalar(select(User))
    adventure = AdventureTemplate(
        id="visual-source-generation",
        owner_id=user.id,
        title="Current presets",
        original_manifest={"visual_presets": SELECTION, "visual_preset_source": "current"},
    )
    db_session.add(adventure)
    await db_session.commit()
    generated = {"teaser": "A quiet room.", "scenes": [{"id": "ROOM"}]}
    await persist_generated_narrative(
        db_session, adventure, adventure.id, generated, "A quiet room", "English", None
    )
    await db_session.refresh(adventure)
    assert adventure.original_manifest["visual_preset_source"] == "current"
    assert adventure.original_manifest["visual_presets"] == SELECTION
    assert adventure.original_manifest["scenes"] == generated["scenes"]
