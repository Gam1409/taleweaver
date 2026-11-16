"""Editor image copies and bundles enforce the same source-image boundary."""

import pytest

from backend.api.routes.adventures.editing.image_clone import _clone_entity_image
from backend.api.routes.adventures.entity_transfer_service import export_entity_bundle
from backend.core.config import settings
from backend.engine.entity_bundle import unpack_entity_bundle
from backend.models import WorldEntity
from backend.models.adventure_template import AdventureTemplate
from tests.test_session_asset_access import image_bytes, write_file


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relative,data",
    [
        ("logs/private.json", b"neutral private fixture"),
        ("adventures/library/OWN/renamed.png", b"neutral private fixture"),
        ("adventures/library/OTHER/portrait.png", image_bytes()),
    ],
)
async def test_editor_clone_rejects_non_images_and_foreign_sources(
    tmp_path, monkeypatch, relative, data
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    write_file(tmp_path, relative, data)
    copied_url = await _clone_entity_image(
        source_image_url="/data/" + relative, template_id="OWN", new_entity_id="GUIDE_1"
    )
    assert copied_url is None


@pytest.mark.parametrize(
    "relative,data",
    [
        ("adventures/library/OWN/renamed.png", b"neutral private fixture"),
        ("adventures/library/OTHER/portrait.png", image_bytes()),
        ("adventures/sessions/other-session/portrait.png", image_bytes()),
    ],
)
def test_entity_bundle_cannot_export_invalid_or_foreign_image_bytes(
    tmp_path, monkeypatch, relative, data
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    write_file(tmp_path, relative, data)
    entity = WorldEntity(
        id="GUIDE",
        entity_type="NPC",
        template_id="OWN",
        name="Guide",
        image_url="/data/" + relative,
    )
    bundle = unpack_entity_bundle(
        export_entity_bundle(AdventureTemplate(id="OWN", title="Own"), entity)
    )
    assert bundle.image_bytes is None
