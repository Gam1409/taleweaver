"""Canonical initial outfits and bounded appearance instructions for world generation."""

from copy import deepcopy
from typing import Any

from backend.core.game_modes import mode_policy
from backend.engine.clothing.profiles import reconcile_profile, sanitize_garment
from backend.engine.clothing.settings import clothing_settings

GENERATION_INSTRUCTION = """
CHARACTER APPEARANCE AND CLOTHING:
Use optional visual_profile for the protagonist and each applicable NPC. Record stable
physical identity in appearance (age_years only when explicitly established, hair, eyes,
build, features), separately from clothing. Keep descriptions neutral and non-graphic.
Choose clothing individually from the setting, culture, profession, status, weather and
current circumstances. Do not assign everybody the same outfit, uniform, or underwear set.
Do not invent uniforms just because someone has a profession. Non-humanoid characters do
not need human clothing or fabricated human anatomy.
Worn clothes are real canonical objects: declare each garment ONCE in objects with its
clothing metadata (layer 0..4, coverage regions, opaque, underwear, description) and a
single owner. Each worn item_id references that same owned object ID, also present in the
actor's starting_inventory/inventory or existing equipment. Never duplicate a garment in
an inline wardrobe, inventory, and objects. Use visual_profile.worn for clothing layers;
Respect the requested object-count budget and prioritize required gameplay/puzzle items.
Use a compact appropriate outfit, not a mandatory complete kit for every actor. If the
budget cannot represent an outfit with canonical items, leave structured clothing absent
and keep its ordinary visible description; never remove useful objects to fill a wardrobe.
Keep existing gameplay equipment slots unchanged, and leave uncovered_regions empty
unless a visible opening is explicitly part of the initial outfit.
For staged generation, declare garments and owners in the compact plan; keep each actor's
individual appearance/outfit facts in their seed summary so all later stages agree.
Omit optional visual_profile/clothing fields for legacy or unspecified appearances rather
than guessing missing personal facts. Clothing settings are author preferences, not output.
"""


def generation_instruction(manifest: Any, *, mode: str = "vn") -> str:
    if not mode_policy(mode).vn:
        return ""
    if clothing_settings(manifest)["detailed"]:
        detail = (
            "Detailed clothing tracking is enabled. Underwear may be represented only for an "
            "actor with an explicitly established appearance.age_years >= 18; otherwise use "
            "outer clothing only. Underwear is ordinary clothing data, not automatically "
            "visible through outer layers. Do not add nudity, erotic framing or arousal mechanics."
        )
    else:
        detail = (
            "Detailed clothing tracking is disabled. Track only ordinary outer clothes and "
            "accessories; omit underwear metadata and underwear from visual_profile.worn. "
            "Do not infer or enumerate hidden garments."
        )
    return GENERATION_INSTRUCTION + "\n" + detail


def _item_id(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    return raw.get("id") if isinstance(raw, dict) else None


def _owned_items(actor: dict, objects: dict[str, dict], protagonist: bool) -> list[dict]:
    inventory = actor.get("starting_inventory" if protagonist else "inventory") or []
    equipment = (
        (actor.get("starting_equipment") or {}).values()
        if protagonist
        else (actor.get("equipped_weapon_id"), actor.get("equipped_armor_id"))
    )
    identifiers = dict.fromkeys(
        identifier for identifier in map(_item_id, [*inventory, *equipment]) if identifier
    )
    return [objects[identifier] for identifier in identifiers if identifier in objects]


def _actor_profile(
    actor: dict, objects: dict[str, dict], protagonist: bool, detailed: bool, blocked: set[str]
) -> None:
    raw = actor.get("visual_profile")
    if raw is None:
        return
    profile = reconcile_profile(raw, _owned_items(actor, objects, protagonist))
    if profile is not None:
        age = (profile.get("appearance") or {}).get("age_years")
        adult = isinstance(age, int) and not isinstance(age, bool) and age >= 18
        profile["worn"] = [
            worn
            for worn in profile.get("worn", [])
            if worn["item_id"] not in blocked
            and objects.get(worn["item_id"], {}).get("clothing")
            and (
                not (objects.get(worn["item_id"], {}).get("clothing") or {}).get("underwear")
                or (detailed and adult)
            )
        ]
    actor["visual_profile"] = profile


def normalize_manifest_clothing(manifest: dict, *, detailed: bool) -> None:
    """Validate supplied facts before portraits; never create or duplicate real items.

    Invalid or disallowed tracking metadata is removed, never the actual inventory
    object. A legacy world without a visual profile stays a legacy world.
    """
    objects = {
        obj["id"]: obj
        for obj in manifest.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    blocked: set[str] = set()
    for obj in objects.values():
        stored = obj.get("metadata_json") if isinstance(obj.get("metadata_json"), dict) else {}
        garment = sanitize_garment(obj.get("clothing") or stored.get("clothing"))
        if garment and garment.get("underwear") and not detailed:
            blocked.add(obj["id"])
            garment = None
        metadata = {key: value for key, value in stored.items() if key != "clothing"}
        obj.pop("clothing", None)
        if garment:
            obj["clothing"] = deepcopy(garment)
            metadata["clothing"] = deepcopy(garment)
        if stored or garment:
            obj["metadata_json"] = metadata
    protagonist = manifest.get("protagonist")
    if isinstance(protagonist, dict):
        _actor_profile(protagonist, objects, True, detailed, blocked)
    for npc in manifest.get("npcs", []):
        if isinstance(npc, dict):
            _actor_profile(npc, objects, False, detailed, blocked)
