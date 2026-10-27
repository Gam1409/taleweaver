"""Static asset selection and procedural placeholder generation."""

import asyncio
import logging
import os
import uuid
from typing import Optional

from backend.core.config import settings
from backend.utils.image_generator import (
    ColorTheme,
    OrganicGradientStrategy,
    PlaceholderImageGenerator,
)

logger = logging.getLogger(__name__)


async def generate_placeholder(
    engine,
    adventure_id: str,
    entity_id: str,
    target_dir: str,
    filename: Optional[str] = None,
    category: str = "",
    theme: Optional[str] = None,
) -> str:
    """Generate placeholders using static SVG assets for NPC/items and PIL for other categories."""
    from backend.engine.media_engine import (
        _ensure_within_data_dir,
        _normalize_output_filename,
        _resolve_output_dir,
    )

    safe_target_dir = target_dir
    try:
        safe_target_dir = _resolve_output_dir(target_dir)
        os.makedirs(safe_target_dir, exist_ok=True)
        cat = category.upper()

        static_svg_url = await engine._copy_static_svg_placeholder(
            target_dir=safe_target_dir,
            entity_id=entity_id,
            category=cat,
            filename=filename,
        )
        if static_svg_url:
            return static_svg_url

        # Determine format and extension
        # Default to PNG for placeholders to preserve transparency if needed,
        # though we currently convert to RGB in the strategy.
        ext = "png"
        if filename:
            if filename.lower().endswith((".jpg", ".jpeg")):
                ext = "jpg"
            elif filename.lower().endswith(".png"):
                ext = "png"

        if not filename:
            filename = f"placeholder_{entity_id}_{uuid.uuid4().hex[:6]}.{ext}"
        filename = _normalize_output_filename(filename, ext)

        filepath = _ensure_within_data_dir(os.path.join(safe_target_dir, filename))

        # Select strategy and theme based on category
        # Map theme string to ColorTheme enum
        color_theme = _placeholder_color_theme(theme)

        if cat in ["SCENE", "COVER", "LANDSCAPE"]:
            # Scenes use random generation with subtle blur
            strategy = OrganicGradientStrategy(theme=color_theme)
            width, height = 1200, 800
        elif cat in ["CHARACTER", "AVATAR"]:
            # Avatars/characters still use the legacy SVG fallback.
            return await engine.generate_svg_placeholder(
                adventure_id, entity_id, safe_target_dir, filename, category
            )
        else:
            strategy = OrganicGradientStrategy(theme=color_theme)
            width, height = 800, 600

        generator = PlaceholderImageGenerator(strategy=strategy)

        # Run in thread pool as PIL operations are blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, generator.create_and_save, filepath, (width, height))

        rel_path = os.path.relpath(filepath, settings.DATA_DIR).replace("\\", "/")
        return f"/data/{rel_path}"
    except (OSError, ValueError, TypeError) as e:
        logger.error("Failed to generate high-quality placeholder: %s", e)
        cat = category.upper()
        # Keep NPC/item placeholders on curated static assets and avoid procedural SVG generation.
        if cat in {"NPC", "ITEM"} or cat.startswith("ITEM_"):
            return ""
        # Fallback to SVG for non-item/non-npc categories.
        return await engine.generate_svg_placeholder(
            adventure_id, entity_id, safe_target_dir, filename, category
        )


def _placeholder_color_theme(theme):
    if not theme:
        return ColorTheme.COLORFUL
    try:
        return ColorTheme[theme.upper()]
    except (KeyError, AttributeError):
        return ColorTheme.COLORFUL
