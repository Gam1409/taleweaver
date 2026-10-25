"""Last-line VN event protection before persistence, including imported sessions."""

from typing import Any

from backend.core.game_modes import is_vn
from backend.engine.rule_engine import GameEvent

_ZERO_FIELDS = ("hp_change", "mana_change", "stamina_change")
_CLEAR_FIELDS = (
    "requested_attacks",
    "attack_results",
    "requested_skill_checks",
    "skill_check_results",
    "new_status_effects",
    "completed_quest_ids",
    "earned_award_keys",
)
_ENTITY_MECHANICS = (
    "hp",
    "max_hp",
    "mana",
    "stamina",
    "stat_modifier_armor_class",
    "is_attackable",
    "is_killable",
    "is_defeated",
)


def enforce_vn_event_policy(event: GameEvent, adventure: Any) -> None:
    """Retain navigation, possessions and observations; suppress RPG outcome mutations."""
    if not is_vn(adventure):
        return
    for field in _ZERO_FIELDS:
        setattr(event, field, 0)
    for field in _CLEAR_FIELDS:
        setattr(event, field, None)
    event.sequence_completed = event.game_completed = event.game_over = False
    for update in event.updated_entities or []:
        for field in _ENTITY_MECHANICS:
            setattr(update, field, None)
