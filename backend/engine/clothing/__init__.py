"""Typed character appearance and deterministic garment visibility."""

from backend.engine.clothing.profiles import (
    load_profile,
    owned_items,
    reconcile_profile,
    sanitize_garment,
    sanitize_inventory,
    validate_profile,
)
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.schema import Appearance, Garment, Region, VisualProfile, WornItem

__all__ = [
    "Appearance",
    "Garment",
    "Region",
    "VisualProfile",
    "WornItem",
    "load_profile",
    "owned_items",
    "reconcile_profile",
    "sanitize_garment",
    "sanitize_inventory",
    "validate_profile",
    "visible_character",
]
