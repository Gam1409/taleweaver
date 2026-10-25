"""Public VN character views exclude authored secrets as well as simulated thoughts."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.game_modes import mode_policy
from backend.engine.npc_journal.records import journal_of
from backend.engine.visual_novel.state import public_profile
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState

PUBLIC_NPC_FIELDS = {
    "id",
    "entity_type",
    "name",
    "description",
    "image_url",
    "current_scene_id",
    "spatial_position",
    "npc_type",
    "voice",
    "is_defeated",
    "is_hidden",
    "is_attackable",
    "is_killable",
    "listed_in_discoveries",
}


async def session_mode(db: AsyncSession, state: SessionState) -> str:
    """Match runtime mode: linked templates stay live; detached sessions use their save."""
    if state.template_id:
        adventure = await db.get(AdventureTemplate, state.template_id)
        if adventure is not None:
            return mode_policy(adventure.rule_enforcement_mode).mode
    snapshot = (state.entity_states or {}).get("__manifest_snapshot__") or {}
    adventure = snapshot.get("adventure") if isinstance(snapshot, dict) else None
    mode = adventure.get("rule_enforcement_mode") if isinstance(adventure, dict) else None
    return mode_policy(mode).mode


async def session_is_vn(db: AsyncSession, state: SessionState) -> bool:
    return await session_mode(db, state) == "vn"


def public_entity(entity: dict[str, Any], state: SessionState) -> dict[str, Any]:
    """Only ordinary player responses use this view; model/save data remain complete."""
    if str(entity.get("entity_type", "")).upper() != "NPC":
        return entity
    result = {key: value for key, value in entity.items() if key in PUBLIC_NPC_FIELDS}
    result["narrative_role"] = (
        "major"
        if public_profile(state, str(entity.get("id")))["importance"] == "hero"
        else "supporting"
    )
    return result


def known_character(npc: Any, state: SessionState) -> bool:
    journal = journal_of(npc)
    if journal.get("introduction") or journal.get("entries"):
        return True
    override = (state.entity_states or {}).get(npc.id) or {}
    if not isinstance(override, dict):
        override = {}
    return (
        not override.get("is_hidden", npc.is_hidden)
        and override.get("current_scene_id", npc.current_scene_id) == state.current_scene_id
    )
