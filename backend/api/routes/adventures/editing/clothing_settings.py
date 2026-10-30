"""Apply author-owned clothing and NSFW preferences in the editor save transaction."""

from fastapi import HTTPException

from backend.core.game_modes import mode_policy
from backend.engine.clothing.editor_conversion import ClothingConversionError, apply_editor_clothing
from backend.engine.clothing.settings import clothing_settings
from backend.engine.nsfw.settings import nsfw_settings, with_nsfw_settings


def apply_nsfw_update(adventure, updates: dict) -> None:
    enabled = updates.pop("nsfw_enabled", None)
    level = updates.pop("nsfw_level", None)
    if enabled is None and level is None:
        return
    current = nsfw_settings(adventure.original_manifest)
    adventure.original_manifest = with_nsfw_settings(
        adventure.original_manifest,
        current["enabled"] if enabled is None else enabled,
        level if level is not None else current["level"],
    )


async def apply_clothing_update(db, adventure, user, updates: dict) -> None:
    # Prepare model-dependent data before dirtying the template. Otherwise an
    # ORM read can autoflush preferences and hold a SQLite writer during inference.
    await _apply_clothing_update(db, adventure, user, updates)
    apply_nsfw_update(adventure, updates)


async def _apply_clothing_update(db, adventure, user, updates: dict) -> None:
    requested = updates.pop("detailed_clothing", None)
    mode = updates.get("rule_enforcement_mode") or adventure.rule_enforcement_mode
    if requested is True and not mode_policy(mode).vn:
        raise HTTPException(422, "Detailed clothing is available in Visual Novel mode only.")
    if requested is None:
        if "rule_enforcement_mode" not in updates or mode_policy(mode).vn:
            return
        if not clothing_settings(adventure.original_manifest)["detailed"]:
            return
        requested = False
    try:
        await apply_editor_clothing(db, adventure, requested, user=user)
    except ClothingConversionError as exc:
        await db.rollback()
        raise HTTPException(
            502,
            str(exc),
        ) from exc
