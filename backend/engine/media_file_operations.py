"""Blocking image and filesystem operations executed by media worker threads."""

import base64
import io
import logging
import os
import re
import shutil
import uuid
from typing import Optional

from PIL import Image

from backend.core.config import settings
from backend.utils.path_security import sanitize_relative_segment
from backend.utils.svg_generator import SVGPlaceholderGenerator

logger = logging.getLogger(__name__)


def _copy_static_svg_placeholder(
    target_dir: str,
    entity_id: str,
    category: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Copy a curated static SVG placeholder into DATA_DIR and return its /data URL."""
    from backend.engine.media_engine import (
        _ensure_within_data_dir,
        _normalize_svg_filename,
        _resolve_output_dir,
        _select_static_placeholder_asset,
    )

    source_asset = _select_static_placeholder_asset(category)
    if not source_asset:
        return None
    if not os.path.exists(source_asset):
        logger.warning("Static SVG placeholder asset not found: %s", source_asset)
        return None

    safe_target_dir = _resolve_output_dir(target_dir)
    os.makedirs(safe_target_dir, exist_ok=True)

    default_stem = f"placeholder_{entity_id}_{uuid.uuid4().hex[:6]}"
    safe_filename = _normalize_svg_filename(filename, default_stem)
    filepath = _ensure_within_data_dir(os.path.join(safe_target_dir, safe_filename))
    shutil.copyfile(source_asset, filepath)

    rel_path = os.path.relpath(filepath, settings.DATA_DIR).replace("\\", "/")
    return f"/data/{rel_path}"


def cleanup_adventure_assets(adventure_id: str) -> None:
    """Removes all generated assets for an adventure from disk."""
    from backend.engine.media_engine import (
        _safe_data_path,
    )

    target_dir = _safe_data_path("adventures", "library", adventure_id)
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
            logger.info("Cleaned up assets for adventure %s", adventure_id)
        except OSError as e:
            logger.error("Failed to cleanup assets for adventure %s: %s", adventure_id, e)


def _generate_thumbnail(filepath: str, max_size: int = 480) -> str | None:
    """Creates a thumbnail for the given image file if it doesn't exist."""
    from backend.engine.media_engine import (
        _ensure_within_data_dir,
        _is_svg_image_file,
    )

    try:
        if ".." in filepath:
            raise ValueError("Path traversal detected")
        safe_filepath = _ensure_within_data_dir(filepath)
        source_stem, ext = os.path.splitext(os.path.basename(safe_filepath))
        safe_thumb_name = sanitize_relative_segment(f"{source_stem}_thumb{ext}")
        if not safe_thumb_name:
            raise ValueError("Invalid thumbnail filename.")
        thumb_path = _ensure_within_data_dir(
            os.path.join(os.path.dirname(safe_filepath), safe_thumb_name)
        )
        # Re-verify containment at the sink so the taint analysis trusts the path.
        data_root = os.path.realpath(settings.DATA_DIR)
        if os.path.commonpath([os.path.realpath(thumb_path), data_root]) != data_root:
            raise ValueError("Invalid thumbnail path: escapes DATA_DIR.")
        # Avoid re-generating if it already exists
        if os.path.exists(thumb_path):
            return thumb_path

        if _is_svg_image_file(safe_filepath, ext):
            shutil.copy2(safe_filepath, thumb_path)
            return thumb_path

        def _resize() -> str:
            with Image.open(safe_filepath) as img:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                img_to_save = (
                    img.convert("RGB")
                    if img.mode in ("RGBA", "P") and ext.lower() in (".jpg", ".jpeg")
                    else img
                )
                img_to_save.save(thumb_path, optimize=True, quality=80)
            return thumb_path

        return _resize()
    except Exception as e:
        logger.error("Failed to generate thumbnail for %s: %s", filepath, e)
        return None


def generate_svg_placeholder(
    adventure_id: str,
    entity_id: str,
    target_dir: str,
    filename: Optional[str] = "placeholder.svg",
    category: str = "",
) -> str:
    """
    Generates a procedural SVG placeholder as a fallback.
    Ensures consistent visual style for 'unmanifested' content.
    """
    from backend.engine.media_engine import (
        _ensure_within_data_dir,
        _normalize_svg_filename,
        _resolve_output_dir,
    )

    _ = adventure_id
    try:
        safe_target_dir = _resolve_output_dir(target_dir)
        os.makedirs(safe_target_dir, exist_ok=True)
        default_stem = f"placeholder_{entity_id}_{uuid.uuid4().hex[:6]}"
        safe_filename = _normalize_svg_filename(filename, default_stem)

        filepath = _ensure_within_data_dir(os.path.join(safe_target_dir, safe_filename))
        generator = SVGPlaceholderGenerator(width=1200, height=800, num_shapes=15)
        generator.save(filepath, title=entity_id, category=category)

        rel_path = os.path.relpath(filepath, settings.DATA_DIR).replace("\\", "/")
        return f"/data/{rel_path}"
    except (OSError, ValueError, TypeError) as e:
        logger.error("Failed to generate SVG placeholder: %s", e)
        return ""


def decode_image_payload(payload: str) -> bytes:
    if payload.startswith("data:image/") and "," in payload:
        payload = payload.split(",", 1)[1]
    payload = re.sub(r"[^A-Za-z0-9+/=]", "", payload)
    payload += "=" * (-len(payload) % 4)
    return base64.b64decode(payload)


def persist_image_bytes(filepath: str, content: bytes, image_format: str, quality: int) -> None:
    if len(content) > 32 * 1024 * 1024:
        raise ValueError("Image exceeds the 32 MiB limit.")
    with Image.open(io.BytesIO(content)) as probe:
        if probe.width * probe.height > 32_000_000:
            raise ValueError("Image exceeds the 32 megapixel limit.")
        probe.verify()
    with Image.open(io.BytesIO(content)) as source:
        target_format = "JPEG" if image_format.lower() == "jpeg" else "PNG"
        image = source.convert("RGB") if target_format == "JPEG" else source
        try:
            image.save(filepath, target_format, quality=quality, optimize=True)
        finally:
            if image is not source:
                image.close()


def list_thumbnail_sources(target_dir: str) -> list[str]:
    return [
        os.path.join(root, name)
        for root, _, files in os.walk(target_dir)
        for name in files
        if os.path.splitext(name)[1].lower() in {".jpg", ".jpeg", ".png"}
        and not os.path.splitext(name)[0].endswith("_thumb")
    ]
