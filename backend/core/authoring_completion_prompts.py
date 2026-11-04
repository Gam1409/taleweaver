"""One typed completion contract shared by manual and post-generation AI fixes."""

import json

from backend.schemas.authoring_completion import CharacterCompletion, WearableCompletion


def _compact_schema(value: object) -> object:
    if isinstance(value, dict):
        result = {
            key: _compact_schema(child)
            for key, child in value.items()
            if key not in {"title", "description", "properties"}
        }
        if "properties" in value:
            result["properties"] = {
                key: _compact_schema(child) for key, child in value["properties"].items()
            }
        return result
    if isinstance(value, list):
        return [_compact_schema(child) for child in value]
    return value


def completion_contract() -> str:
    return (
        """
AUTHORING COMPLETION (extends the basic patch contract):
Complete missing data according to the existing setting, biography and scene. Preserve
established facts and valid traits. Optional unknown gender/age may remain unknown; never
infer adulthood from appearance. Do not fill slots indiscriminately: no default rings,
weapons, armor or identical outfits for every character.
For mature-enabled worlds with detailed clothing and an ALREADY established adult age,
include appropriate inner layers as ordinary owned clothing (underwear=true, correct layer
and coverage), not exposed anatomy. Check inner layers as well as outer clothes. Preserve
explicit story exceptions. For minors, unknown ages or disabled settings, do not add inner
layers. A new age proposed by this fix does not establish eligibility for inner layers.
Use npc.personality_profile for seven structured tendencies (schema enum choices), not
prose in character. Preserve valid existing values and fill only absent/invalid ones.
Use appearance for stable visual identity, not clothing; preserve the biography's visual
facts when preparing a legacy character. Supply appearance together with the first outfit.
Use outfit to add a compact ordinary outfit when appropriate. Prefer existing OWNED garments
by item_id; never take someone else's items. If the described garment does not exist, omit
item_id and provide name, description, wearable_slots, clothing: the server creates a real
owned item and links it to worn clothing and free equipment slots. Do not invent IDs.
Outfit completion adds to the existing outfit; it never undresses or replaces equipment.
For characters who intentionally need no clothes (animals, incorporeal beings, or explicit
story facts), set outfit_exemption to a short reason rather than inventing human clothing.
An intentional exemption must not be used to avoid completing an ordinary missing outfit.
For existing WEARABLE objects fill wearable_slots and clothing metadata; no gameplay bonuses.
Descriptions should be concrete, in the adventure's language. For scene quality findings,
provide spatial layout, lighting, atmosphere and useful existing landmarks. Preserve all
clues, exits, actors and established physical facts; do not add unregistered interactables.
The character completion schema describes only the EXTRA allowed field_updates keys for
npc/protagonist, alongside the original narrative fields. The wearable schema extends objects.
CHARACTER COMPLETION SCHEMA:
"""
        + json.dumps(
            _compact_schema(CharacterCompletion.model_json_schema()),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\nWEARABLE COMPLETION SCHEMA:\n"
        + json.dumps(
            _compact_schema(WearableCompletion.model_json_schema()),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
