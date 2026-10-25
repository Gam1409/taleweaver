"""Capability policy shared by generation, persistence and the game loop."""

from dataclasses import dataclass
from typing import Any

VN_OPTIONAL_STORY_FIELDS = ("walkthrough", "completed_condition", "gameover_condition")


@dataclass(frozen=True)
class ModePolicy:
    mode: str
    vn: bool
    mechanics: bool
    combat: bool
    quests: bool
    awards: bool
    experience: bool


def mode_policy(mode: str | None, strict_rules: bool | None = None) -> ModePolicy:
    """Keep legacy strict-flag precedence while VN always disables RPG mechanics."""
    resolved = mode or "rpg"
    if resolved == "vn":
        return ModePolicy(resolved, True, False, False, False, False, False)
    mechanics = resolved != "chat" if strict_rules is None else bool(strict_rules)
    return ModePolicy(
        resolved, False, mechanics, resolved == "rpg", resolved != "chat", resolved != "chat", True
    )


def is_vn(adventure: Any) -> bool:
    """Accept a template or an adventure snapshot without loading ORM relationships."""
    mode = (
        adventure.get("rule_enforcement_mode")
        if isinstance(adventure, dict)
        else getattr(adventure, "rule_enforcement_mode", None)
    )
    return mode_policy(mode).vn


def normalize_vn_template(adventure: Any) -> None:
    """Keep imported or edited VN templates consistent with their persisted mode."""
    if not is_vn(adventure):
        return
    defaults = {
        "strict_rules": False,
        "can_damage_npcs": False,
        "npcs_can_damage_protagonist": False,
        "quest_generation_enabled": False,
        "award_generation_enabled": False,
        "scripts_generation_enabled": False,
        "quests": [],
        "awards": [],
        "sequences": [],
        **dict.fromkeys(VN_OPTIONAL_STORY_FIELDS, ""),
        "completed_guard_expression": "",
        "gameover_guard_expression": "",
    }
    for field, value in defaults.items():
        setattr(adventure, field, value)
    original = getattr(adventure, "original_manifest", None)
    if not isinstance(original, dict):
        return
    manifest = {**original, **defaults, "rule_enforcement_mode": "vn"}
    if isinstance(original.get("adventure"), dict):
        manifest["adventure"] = {**original["adventure"], **defaults, "rule_enforcement_mode": "vn"}
    adventure.original_manifest = manifest
