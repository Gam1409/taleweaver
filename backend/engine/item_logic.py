from typing import Optional


def get_item_slot(name: str, item_type: str) -> Optional[str]:
    """
    Attempts to determine the appropriate equipment slot for an item based on its name and type.
    Returns None if the item is not equippable or no slot can be determined.
    """
    if not name or not item_type:
        return None

    type_upper = item_type.upper()
    name_lower = name.lower()

    # Weapons always go to MainHand by default
    if type_upper == "WEAPON":
        return "MainHand"

    if type_upper == "WEARABLE":
        return _wearable_slot(name_lower)

    # Tools might go to OffHand if they are held
    if type_upper == "TOOL":
        if any(kw in name_lower for kw in ["shield", "buckler", "torch", "lantern"]):
            return "OffHand"
        return "MainHand"  # Pickaxes, hammers, etc.

    return None


def _wearable_slot(name_lower: str) -> Optional[str]:
    """Match wearable keywords in their original precedence order."""
    slot_keywords = (
        ("Hands", ("bracers", "gauntlets", "gloves", "mittens", "vambrace", "armguard")),
        ("Head", ("helmet", "cap", "circlet", "crown", "hood", "hat", "mask", "head")),
        (
            "Chest",
            ("armor", "chest", "cuirass", "vest", "tunic", "robe", "shirt", "breastplate", "plate"),
        ),
        ("Legs", ("greaves", "leggings", "pants", "trousers", "breeches")),
        ("Feet", ("boots", "shoes", "sandals", "slippers", "footwear")),
        ("Ring_1", ("ring", "band", "signet")),
        ("Neck", ("amulet", "necklace", "pendant", "locket", "talisman")),
    )
    for slot, keywords in slot_keywords:
        if any(keyword in name_lower for keyword in keywords):
            return slot
    return None


def normalize_equipment_keys(equipment: Optional[dict]) -> dict:
    """Normalizes equipment slot keys to the standard PascalCase keys expected by the frontend."""
    if not equipment:
        return {
            "Head": None,
            "Chest": None,
            "Arms": None,
            "Legs": None,
            "Hands": None,
            "Feet": None,
            "Ring_1": None,
            "Ring_2": None,
            "Neck": None,
            "MainHand": None,
            "OffHand": None,
        }

    key_mapping = {
        "head": "Head",
        "chest": "Chest",
        "arms": "Arms",
        "legs": "Legs",
        "hands": "Hands",
        "feet": "Feet",
        "ring_1": "Ring_1",
        "ring_2": "Ring_2",
        "neck": "Neck",
        "main_hand": "MainHand",
        "mainhand": "MainHand",
        "off_hand": "OffHand",
        "offhand": "OffHand",
    }

    normalized = {
        "Head": None,
        "Chest": None,
        "Arms": None,
        "Legs": None,
        "Hands": None,
        "Feet": None,
        "Ring_1": None,
        "Ring_2": None,
        "Neck": None,
        "MainHand": None,
        "OffHand": None,
    }

    for k, v in equipment.items():
        mapped_key = key_mapping.get(k.lower(), k)
        if mapped_key in normalized:
            normalized[mapped_key] = v

    return normalized
