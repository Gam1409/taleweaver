"""Conservative authoring gaps; prose quality and clothing applicability need AI review."""

from pydantic import ValidationError

from backend.core.world_validation.context import (
    ValidationContext,
    entity_field,
    entity_kind,
    finding,
)
from backend.engine.authoring_clothing_policy import allows_inner_layers
from backend.engine.clothing.profiles import owned_items
from backend.engine.clothing.schema import Garment, VisualProfile
from backend.engine.personality.profile import CATALOG, read_profile
from backend.schemas.validation import ValidationFinding


def _actor_metadata(actor: dict) -> dict:
    raw = actor.get("metadata_json") or actor.get("stats")
    return raw if isinstance(raw, dict) else {}


def _is_inner(item: dict) -> bool:
    raw = entity_field(item, "clothing")
    return isinstance(raw, dict) and raw.get("underwear") is True


def _character_gaps(actor: dict, *, npc: bool) -> list[str]:
    missing = [
        key for key in ("description", "goal", "character") if not str(actor.get(key) or "").strip()
    ]
    if npc:
        traits = read_profile(actor).model_dump()
        missing += [f"personality_profile.{key}" for key in CATALOG if not traits[key]]
    exemption = _actor_metadata(actor).get("outfit_exemption")
    raw = actor.get("visual_profile")
    if raw is None:
        if not exemption:
            missing.append("visual_profile")
        return missing
    try:
        profile = VisualProfile.model_validate(raw)
    except ValidationError:
        missing.append("visual_profile.invalid")
        return missing
    if not any(getattr(profile.appearance, key) for key in ("hair", "eyes", "build", "features")):
        missing.append("appearance")
    if not profile.worn and not exemption:
        missing.append("outfit.review")
    return missing


def check_authoring_completeness(ctx: ValidationContext) -> list[ValidationFinding]:
    result = []
    actors = [
        (f"npc:{actor.get('id')}", actor, True)
        for actor in ctx.entities
        if entity_kind(actor) == "NPC"
    ]
    if ctx.protagonist:
        actors.insert(0, ("protagonist:player", ctx.protagonist, False))
    for location, actor, npc in actors:
        missing = _character_gaps(actor, npc=npc)
        if not npc and _missing_equipment_slots(ctx, actor):
            missing.append("equipment.worn_slots")
        if _needs_inner_layer_review(ctx, actor):
            missing.append("outfit.inner_layers_review")
        if missing:
            result.append(
                finding(
                    "warn",
                    "character_details_incomplete",
                    f"{actor.get('name') or location}: review missing character details ({', '.join(missing)}). "
                    "An empty outfit can be intentional; never fill every equipment slot by default.",
                    location,
                    missing_fields=missing,
                    optional_identity_fields=[
                        key for key in ("gender", "age_years") if actor.get(key) is None
                    ],
                )
            )
    for scene in ctx.scenes:
        if not str(scene.get("description") or "").strip():
            result.append(
                finding(
                    "warn",
                    "scene_description_missing",
                    "Scene needs a playable description: layout, visible details and usable landmarks.",
                    f"scene:{scene.get('id')}",
                    missing_fields=["description"],
                )
            )
    return result + _wearable_gaps(ctx)


def _wearable_gaps(ctx: ValidationContext) -> list[ValidationFinding]:
    result = []
    for item in ctx.entities:
        if str(item.get("item_type") or "").upper() != "WEARABLE":
            continue
        missing = []
        if not item.get("wearable_slots"):
            missing.append("wearable_slots")
        try:
            Garment.model_validate(entity_field(item, "clothing"))
        except ValidationError:
            missing.append("clothing")
        if missing:
            result.append(
                finding(
                    "warn",
                    "wearable_details_incomplete",
                    f"{item.get('name') or item.get('id')}: missing or invalid wearable metadata.",
                    f"object:{item.get('id')}",
                    missing_fields=missing,
                )
            )
    return result


def _needs_inner_layer_review(ctx: ValidationContext, actor: dict) -> bool:
    if not allows_inner_layers(ctx.adventure.get("original_manifest"), actor):
        return False
    if _actor_metadata(actor).get("outfit_exemption"):
        return False
    profile = actor.get("visual_profile")
    if not isinstance(profile, dict):
        return False
    worn = profile.get("worn") or []
    if not isinstance(worn, list):
        return False
    items = _wardrobe_items(ctx, actor)
    return not any(
        _is_inner(items.get(str(entry.get("item_id") or ""), {}))
        for entry in worn
        if isinstance(entry, dict)
    )


def _missing_equipment_slots(ctx: ValidationContext, actor: dict) -> bool:
    profile = actor.get("visual_profile")
    if not isinstance(profile, dict):
        return False
    equipment = actor.get("equipment") or {}
    if not isinstance(equipment, dict):
        return True
    worn = profile.get("worn") or []
    if not isinstance(worn, list):
        return False
    worn_ids = {str(row.get("item_id")) for row in worn if isinstance(row, dict)}
    items = [item for key, item in _wardrobe_items(ctx, actor).items() if key in worn_ids]
    return any(not equipment.get(slot) for item in items for slot in _wearable_slots(item))


def _wearable_slots(item: dict) -> list[str]:
    raw = item.get("wearable_slots")
    return [value for value in raw if isinstance(value, str)] if isinstance(raw, list) else []


def _wardrobe_items(ctx: ValidationContext, actor: dict) -> dict[str, dict]:
    """Resolve worn references from inline items and canonical object records."""
    owned = owned_items(actor.get("inventory"), equipment=actor.get("equipment"))
    return {**owned, **ctx.entities_by_id}
