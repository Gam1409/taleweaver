"""Map exact body-part identifiers to existing display positions without changing the ledger."""

from backend.engine.physical_conditions.schema import Condition

_PARTS = {
    "Head": ("head", "neck", "face", "scalp"),
    "Chest": ("torso", "chest", "back", "abdomen", "stomach"),
    "Arms": ("arm", "arms", "left_arm", "right_arm", "left arm", "right arm"),
    "Hands": ("hand", "hands", "left_hand", "right_hand", "left hand", "right hand"),
    "Legs": ("pelvis", "leg", "legs", "left_leg", "right_leg", "left leg", "right leg"),
    "Feet": ("foot", "feet", "left_foot", "right_foot", "left foot", "right foot"),
    "BodyVaginal": ("vaginal", "vagina", "clitoris", "labia", "vulva"),
    "BodyAnal": ("anal", "anus", "sphincter", "anal_sphincter", "anal sphincter"),
    "BodyUterine": ("uterine", "uterus"),
    "BodyPenile": ("penile", "penis", "testicle", "testicles", "testis", "testes"),
}
_PART_SLOT = {part: slot for slot, parts in _PARTS.items() for part in parts}


def condition_position(
    row: Condition, actor_id: str, placement: dict, *, source_confirmed: bool
) -> dict:
    """Unknown parts and item targets stay in the general list under existing visibility rules."""
    if row.target_id != actor_id:
        return {}
    slot = _PART_SLOT.get(row.part.strip().casefold())
    if slot is None:
        return {}
    if slot.startswith("Body") and not _reported_group(slot, placement, source_confirmed):
        return {}
    return {"display_slots": [slot]}


def _reported_group(slot: str, placement: dict, source_confirmed: bool) -> bool:
    if not source_confirmed:
        return False
    return placement.get("placement_status") == "unassessed" or slot in {
        entry["key"] for entry in placement.get("placement_slots", [])
    }
