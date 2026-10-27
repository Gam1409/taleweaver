import logging
from copy import deepcopy

from sqlalchemy import select

from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.item_logic import normalize_equipment_keys
from backend.models.avatar import Avatar

logger = logging.getLogger(__name__)


async def resolve_start_avatar(db, template_id, current_user, adventure):
    # 1. Resolve Avatar (Template-based or fresh manifest-based)
    av_res = await db.execute(
        select(Avatar)
        .where(Avatar.template_id == template_id)
        .order_by(Avatar.created_at.asc())
        .limit(1)
    )
    template_avatar = av_res.scalars().first()

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
            visual_profile=deepcopy(template_avatar.visual_profile),
            profile_image=template_avatar.profile_image,
            hp=template_avatar.hp,
            max_hp=template_avatar.max_hp,
            stamina=template_avatar.stamina,
            max_stamina=template_avatar.max_stamina,
            mana=template_avatar.mana,
            max_mana=template_avatar.max_mana,
            strength=template_avatar.strength,
            dexterity=template_avatar.dexterity,
            intelligence=template_avatar.intelligence,
            wisdom=template_avatar.wisdom,
            charisma=template_avatar.charisma,
            armor_class=template_avatar.armor_class,
            stats=deepcopy(template_avatar.stats or {}),
            inventory=deepcopy(template_avatar.inventory or []),
            equipment=normalize_equipment_keys(template_avatar.equipment),
            status_effects=deepcopy(template_avatar.status_effects or []),
        )
    else:
        # Fallback: Create from manifest if no template avatar exists (legacy/import)
        prot = (adventure.original_manifest or {}).get("protagonist", {})
        avatar = Avatar(
            user_id=current_user.id,
            template_id=template_id,
            name=prot.get("name", "You"),
            role=prot.get("role"),
            description=prot.get("description"),
            goal=prot.get("goal"),
            character=prot.get("character"),
            visual_profile=deepcopy(prot.get("visual_profile")),
            profile_image=prot.get("profile_image"),
            hp=prot.get("hp", 200),
            max_hp=prot.get("hp", 200),
            stamina=prot.get("stamina", 200),
            max_stamina=prot.get("stamina", 200),
            mana=prot.get("mana", 200),
            max_mana=prot.get("mana", 200),
            strength=prot.get("strength", 10),
            dexterity=prot.get("dexterity", 10),
            intelligence=prot.get("intelligence", 10),
            wisdom=prot.get("wisdom", 10),
            charisma=prot.get("charisma", 10),
            armor_class=prot.get("armor_class", 10),
            stats=prot.get("stats", {}),
            inventory=deepcopy(prot.get("starting_inventory") or prot.get("inventory", [])),
            equipment=normalize_equipment_keys(prot.get("starting_equipment")),
            status_effects=deepcopy(prot.get("status_effects", [])),
        )

    return avatar
