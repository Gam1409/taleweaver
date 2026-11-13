import logging
from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.world import AdventureLogic
from backend.engine.item_logic import normalize_equipment_keys
from backend.engine.template_avatar import avatar_from_manifest, get_template_avatar
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.user import User

logger = logging.getLogger(__name__)


async def resolve_start_avatar(
    db: AsyncSession, template_id: str, current_user: User, adventure: AdventureTemplate
) -> Avatar:
    # 1. Resolve Avatar (Template-based or fresh manifest-based)
    template_avatar = await get_template_avatar(db, template_id)

    if template_avatar:
        # Heal template avatar image on the fly if corrupted
        healed_image = AdventureLogic.heal_template_avatar_profile_image(
            template_id, template_avatar.profile_image
        )
        if healed_image != template_avatar.profile_image:
            template_avatar.profile_image = healed_image
            db.add(template_avatar)
            await db.flush()

        # Clone template avatar for this session
        avatar = Avatar(
            user_id=current_user.id,
            template_id=template_id,
            name=template_avatar.name,
            role=template_avatar.role,
            description=template_avatar.description,
            goal=template_avatar.goal,
            character=template_avatar.character,
            gender=template_avatar.gender,
            age_years=template_avatar.age_years,
            visual_profile=deepcopy(template_avatar.visual_profile),
            profile_image=template_avatar.profile_image,
            hp=template_avatar.hp,
            max_hp=template_avatar.max_hp,
            stamina=template_avatar.stamina,
            max_stamina=template_avatar.max_stamina,
            mana=template_avatar.mana,
            max_mana=template_avatar.max_mana,
            exp=template_avatar.exp,
            strength=template_avatar.strength,
            dexterity=template_avatar.dexterity,
            intelligence=template_avatar.intelligence,
            wisdom=template_avatar.wisdom,
            charisma=template_avatar.charisma,
            armor_class=template_avatar.armor_class,
            stats=deepcopy(template_avatar.stats or {}),
            inventory=deepcopy(template_avatar.inventory or []),
            equipment=normalize_equipment_keys(deepcopy(template_avatar.equipment)),
            status_effects=deepcopy(template_avatar.status_effects or []),
        )
    else:
        # Fallback: Create from manifest if no template avatar exists (legacy/import)
        avatar = avatar_from_manifest(
            adventure.original_manifest, user_id=current_user.id, template_id=template_id
        )

    return avatar
