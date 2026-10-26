"""Apply author-owned clothing preferences in the ordinary editor save transaction."""

from fastapi import HTTPException

from backend.core.game_modes import mode_policy
from backend.engine.clothing.editor_conversion import ClothingConversionError, apply_editor_clothing
from backend.engine.clothing.settings import clothing_settings


async def apply_clothing_update(db, adventure, user, updates: dict) -> None:
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
