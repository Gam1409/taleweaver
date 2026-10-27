"""Validate and restore ADZ archives, including their bundled image assets."""

import io
import json
import logging
import os
import zipfile
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.adventure_format import validate_manifest_version
from backend.core.config import settings
from backend.core.game_modes import mode_policy, normalize_vn_template
from backend.engine.import_archive_world import build_archive_world
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.utils.text_utils import generate_adventure_id

logger = logging.getLogger(__name__)


def _map_archive_images(manifest_data, prot, existing_images_mapping):
    image_urls = {}
    if prot and prot.get("profile_image") in existing_images_mapping:
        image_urls["PROTAGONIST"] = existing_images_mapping[prot["profile_image"]]
    for s in manifest_data.get("scenes", []):
        if s.get("image_url") in existing_images_mapping:
            image_urls[s["id"]] = existing_images_mapping[s["image_url"]]
    for n in manifest_data.get("npcs", []):
        if n.get("image_url") in existing_images_mapping:
            image_urls[n["id"]] = existing_images_mapping[n["image_url"]]
    for o in manifest_data.get("objects", []):
        if o.get("image_url") in existing_images_mapping:
            image_urls[o["id"]] = existing_images_mapping[o["image_url"]]

    return image_urls


def _extract_archive_assets(zip_file, new_template_id):
    from backend.engine.adventure_importer import _ensure_within_data_dir

    target_base_dir = _ensure_within_data_dir(
        os.path.join(settings.DATA_DIR, "adventures", "library", new_template_id)
    )
    os.makedirs(target_base_dir, exist_ok=True)

    existing_images_mapping = {}  # zip_path -> local_url
    for zip_path in zip_file.namelist():
        if zip_path.startswith("assets/"):
            filename = os.path.basename(zip_path)
            if not filename:
                continue
            target_path = _ensure_within_data_dir(os.path.join(target_base_dir, filename))
            with open(target_path, "wb") as f:
                f.write(zip_file.read(zip_path))

            rel_path = os.path.relpath(target_path, settings.DATA_DIR).replace("\\", "/")
            existing_images_mapping[zip_path] = f"/data/{rel_path}"

    return existing_images_mapping


async def _resolve_archive_conflict(db, owner_id, origin_id, adv_data, overwrite):
    from backend.engine.adventure_importer import AdventureConflictError, AdventureTemplateImporter

    query = select(AdventureTemplate).where(
        (AdventureTemplate.owner_id == owner_id)
        if owner_id
        else (AdventureTemplate.owner_id.is_(None))
    )
    if origin_id:
        query = query.where(
            (AdventureTemplate.title == adv_data["title"])
            | (AdventureTemplate.origin_id == origin_id)
        )
    else:
        query = query.where(AdventureTemplate.title == adv_data["title"])

    existing_res = await db.execute(query)
    existing = existing_res.scalars().first()
    if existing:
        if not overwrite:
            raise AdventureConflictError(
                title=adv_data["title"],
                existing_version=existing.version,
                new_version=adv_data.get("version"),
                template_id=existing.id,
            )
        else:
            logger.info(f"Overwriting existing adventure '{adv_data['title']}'...")
            await AdventureTemplateImporter.delete_template_for_overwrite(db, existing.id)


def _archive_sizes_allowed(zip_file):
    from backend.engine.adventure_importer import (
        MAX_ADZ_COMPRESSION_RATIO,
        MAX_ADZ_ENTRY_BYTES,
        MAX_ADZ_TOTAL_BYTES,
        MAX_ADZ_TOTAL_ENTRIES,
    )

    infos = zip_file.infolist()

    # Zip-bomb / resource-exhaustion guards.
    if len(infos) > MAX_ADZ_TOTAL_ENTRIES:
        logger.error(
            "Refusing ADZ import: %d entries exceeds limit of %d.",
            len(infos),
            MAX_ADZ_TOTAL_ENTRIES,
        )
        return False

    total_uncompressed = 0
    for info in infos:
        if info.file_size > MAX_ADZ_ENTRY_BYTES:
            logger.error(
                "Refusing ADZ import: entry '%s' is %d bytes (limit %d).",
                info.filename,
                info.file_size,
                MAX_ADZ_ENTRY_BYTES,
            )
            return False
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ADZ_TOTAL_BYTES:
            logger.error(
                "Refusing ADZ import: total uncompressed size exceeds %d bytes.",
                MAX_ADZ_TOTAL_BYTES,
            )
            return False
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_ADZ_COMPRESSION_RATIO:
                logger.error(
                    "Refusing ADZ import: entry '%s' compression ratio %.1fx exceeds %dx.",
                    info.filename,
                    ratio,
                    MAX_ADZ_COMPRESSION_RATIO,
                )
                return False

    return True


def _read_archive_manifest(zip_file):
    if "adventure.adv" not in zip_file.namelist():
        logger.error("Invalid ADZ: Missing adventure.adv")
        return None

    manifest_data = json.loads(zip_file.read("adventure.adv").decode("utf-8"))
    try:
        validate_manifest_version(manifest_data, require_format=True)
    except ValueError as exc:
        logger.error("Invalid ADZ format: %s", exc)
        return None

    adv_data = manifest_data.get("adventure")
    if not adv_data:
        logger.error("Invalid ADZ: Missing adventure section in manifest")
        return None

    return manifest_data


async def import_adz(
    db: AsyncSession, adz_data: bytes, owner_id: Optional[str] = None, overwrite: bool = False
) -> bool:
    """Logic for ADZ (ZIP) import, including assets."""
    from backend.engine.adventure_importer import (
        AdventureConflictError,
        _resolve_license_url,
    )

    try:
        zip_buffer = io.BytesIO(adz_data)

        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            if not _archive_sizes_allowed(zip_file):
                return False

            manifest_data = _read_archive_manifest(zip_file)
            if manifest_data is None:
                return False
            adv_data = manifest_data["adventure"]

            # Check if template with this title or origin_id already exists for this owner
            origin_id = adv_data.get("origin_id") or manifest_data.get("origin_id")

            await _resolve_archive_conflict(db, owner_id, origin_id, adv_data, overwrite)

            # Create new template ID
            new_template_id = generate_adventure_id(adv_data["title"])

            enforcement_mode = adv_data.get("rule_enforcement_mode", "rpg")
            is_strict = mode_policy(enforcement_mode, adv_data.get("strict_rules")).mechanics

            # Create AdventureTemplate record
            resolved_license = adv_data.get("license") or manifest_data.get("license")
            resolved_license_url = _resolve_license_url(
                adv_data.get("license_url") or manifest_data.get("license_url"),
                resolved_license,
            )
            from backend.engine.import_build_archive_template import build_archive_template

            new_template = build_archive_template(
                new_template_id,
                owner_id,
                adv_data,
                manifest_data,
                origin_id,
                enforcement_mode,
                is_strict,
                resolved_license,
                resolved_license_url,
            )

            normalize_vn_template(new_template)
            db.add(new_template)

            existing_images_mapping = _extract_archive_assets(zip_file, new_template_id)

            world_manifest = build_archive_world(manifest_data, adv_data, resolved_license_url)
            prot = manifest_data.get("protagonist")

            image_urls = _map_archive_images(manifest_data, prot, existing_images_mapping)

            user = None
            if owner_id:
                user_res = await db.execute(select(User).where(User.id == owner_id))
                user = user_res.scalars().first()

            await WorldGenerator.apply_manifest(
                db=db,
                template_id=new_template_id,
                manifest_dict=world_manifest,
                user=user,
                existing_images=image_urls,
            )

            # apply_manifest toggles readiness during persistence; imports must remain ready.
            new_template.is_ready = True
            new_template.creation_status = "Ready"
            new_template.creation_error = None

            if adv_data.get("image_url") in existing_images_mapping:
                new_template.image_url = existing_images_mapping[adv_data["image_url"]]
            else:
                from backend.engine.media_engine import MediaEngine

                new_template.image_url = await MediaEngine.generate_placeholder(
                    new_template_id,
                    new_template.title,
                    os.path.join(settings.DATA_DIR, "adventures", "library", new_template_id),
                    category="COVER",
                )

            await db.commit()
            # Ensure thumbnails are generated for imported assets
            from backend.engine.media_engine import MediaEngine

            await MediaEngine.ensure_thumbnails(new_template_id)
            return True
    except AdventureConflictError:
        raise
    except Exception:
        logger.exception("ADZ Import failed")
        await db.rollback()
        return False
