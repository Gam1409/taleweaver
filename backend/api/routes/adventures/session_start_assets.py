import logging

from sqlalchemy import select

from backend.api.routes.adventures.logic import AdventureLogic
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


async def initialize_session_assets(db, template_id, new_session, avatar, adventure):
    from .sessions import _copy_data_asset_to_session

    asset_copy_cache: dict[str, str] = {}
    copied_cover_url = _copy_data_asset_to_session(
        new_session.id, "cover", adventure.image_url, asset_copy_cache
    )
    copied_protagonist_url = _copy_data_asset_to_session(
        new_session.id, "protagonist", avatar.profile_image, asset_copy_cache
    )

    adventure_image_url = copied_cover_url or adventure.image_url
    protagonist_image_url = copied_protagonist_url or avatar.profile_image

    new_session.adventure_image_url = adventure_image_url
    avatar.profile_image = protagonist_image_url

    # Create SessionState with narrative and asset snapshot
    manifest_snapshot = AdventureLogic.build_session_manifest_snapshot(adventure)

    # Build entity image mapping from template entities for asset snapshot
    ent_rows = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == template_id,
            WorldEntity.session_id.is_(None),
        )
    )
    template_entities = ent_rows.scalars().all()
    entity_images = {}
    for ent in template_entities:
        if not getattr(ent, "id", None):
            continue
        copied_entity_image = _copy_data_asset_to_session(
            new_session.id,
            "entities",
            ent.image_url,
            asset_copy_cache,
        )
        entity_images[ent.id] = copied_entity_image or ent.image_url

    asset_snapshot = {
        "cover": adventure_image_url,
        "protagonist": protagonist_image_url,
        "entity_images": entity_images,
    }

    initial_entity_states = {
        AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: manifest_snapshot,
        "__asset_snapshot__": asset_snapshot,
    }
    for ent in template_entities:
        if str(getattr(ent, "entity_type", "") or "").upper() != "OBJECT":
            continue
        metadata_json = dict(getattr(ent, "metadata_json", None) or {})
        code_to_unlock = metadata_json.get("code_to_unlock")
        item_to_unlock = metadata_json.get("item_to_unlock")
        rule_to_unlock = metadata_json.get("rule_to_unlock")
        if code_to_unlock or item_to_unlock or rule_to_unlock:
            initial_entity_states[ent.id] = {"locked": True}
        else:
            locked = metadata_json.get("locked")
            if isinstance(locked, bool):
                initial_entity_states[ent.id] = {"locked": locked}

    return asset_copy_cache, entity_images, initial_entity_states, template_entities
