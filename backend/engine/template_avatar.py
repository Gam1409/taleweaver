"""Resolve authored protagonists without adopting a saved game's character."""

from copy import deepcopy
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.engine.item_logic import normalize_equipment_keys
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession

# (avatar attribute, manifest key, default for new avatars)
AVATAR_FIELDS: tuple[tuple[str, str, Any], ...] = (
    ("name", "name", "Hero"),
    ("role", "role", "Protagonist"),
    ("description", "description", ""),
    ("goal", "goal", ""),
    ("character", "character", ""),
    ("gender", "gender", None),
    ("age_years", "age_years", None),
    ("visual_profile", "visual_profile", None),
    ("hp", "hp", 200),
    ("max_hp", "hp", 200),
    ("stamina", "stamina", 200),
    ("max_stamina", "stamina", 200),
    ("mana", "mana", 200),
    ("max_mana", "mana", 200),
    ("strength", "strength", 10),
    ("dexterity", "dexterity", 10),
    ("intelligence", "intelligence", 10),
    ("wisdom", "wisdom", 10),
    ("charisma", "charisma", 10),
    ("armor_class", "armor_class", 10),
    ("exp", "exp", 0),
)


def template_avatar_condition(template_id: str) -> ColumnElement[bool]:
    """Session references take precedence over the avatar's cleanup template link."""
    used_by_session = select(GameSession.id).where(GameSession.avatar_id == Avatar.id).exists()
    return (Avatar.template_id == template_id) & ~used_by_session


def template_avatar_query(template_id: str) -> Select[tuple[Avatar]]:
    """Keep deterministic legacy ordering within the authored avatar scope."""
    return (
        select(Avatar)
        .where(template_avatar_condition(template_id))
        .order_by(Avatar.created_at.asc(), Avatar.id.asc())
        .limit(1)
    )


async def get_template_avatar(db: AsyncSession, template_id: str) -> Avatar | None:
    return (await db.execute(template_avatar_query(template_id))).scalars().first()


def avatar_from_manifest(manifest: Any, *, template_id: str, user_id: str | None) -> Avatar:
    """Build an independent fallback from authored data without persisting it."""
    prot = manifest.get("protagonist") if isinstance(manifest, dict) else None
    prot = prot if isinstance(prot, dict) else {}
    values = {
        attr: deepcopy(prot.get(attr, prot.get(key, default)))
        for attr, key, default in AVATAR_FIELDS
    }
    values["name"] = str(values["name"] or "Hero")
    return Avatar(
        user_id=user_id,
        template_id=template_id,
        profile_image=prot.get("profile_image"),
        stats=deepcopy(prot.get("stats") or {}),
        inventory=deepcopy(prot.get("starting_inventory", prot.get("inventory")) or []),
        equipment=normalize_equipment_keys(
            deepcopy(prot.get("starting_equipment", prot.get("equipment")) or {})
        ),
        status_effects=deepcopy(prot.get("status_effects") or []),
        **values,
    )
