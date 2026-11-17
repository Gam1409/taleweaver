"""Shared NPC resource checks for automatic and selected combat actions."""

from typing import Any

from backend.engine.combat.special_attacks import can_afford


def npc_can_afford(action: dict[str, Any], enemy: dict[str, Any]) -> bool:
    """NPCs without a pool for the cost resource keep the legacy free-use rule."""
    if int(enemy.get(f"max_{action['cost_type']}") or 0) <= 0:
        return True
    return can_afford(action, enemy)
