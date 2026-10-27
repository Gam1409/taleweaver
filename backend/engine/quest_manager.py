import logging
from typing import Any, Optional

from backend.engine.hard_rule_evaluator import HardRuleEvaluator
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState

logger = logging.getLogger(__name__)


class QuestManager:
    """
    Deterministic quest evaluation engine that complements the LLM-driven mechanics pass.
    Evaluates both structured hard rules (required item, required scene, required defeated NPC,
    scripting guards) and heuristic keyword goals.
    """

    @classmethod
    def evaluate_quests(
        cls,
        avatar: Avatar,
        state: SessionState,
        new_inventory_items: Optional[list[Any]] = None,
        new_scene_id: Optional[str] = None,
        updated_entities: Optional[list[Any]] = None,
        script_context: Optional[Any] = None,
    ) -> list[str]:
        """
        Evaluates current unresolved quests against the current game state.
        Returns a list of quest IDs that have just been completed.
        """
        if not state.quests:
            return []

        completed_ids = []
        terminal_statuses = {"completed", "failed", "cancelled", "abandoned"}
        open_quests = [
            q for q in state.quests if str(q.get("status") or "").lower() not in terminal_statuses
        ]

        for quest in open_quests:
            qid = quest.get("id")
            if not qid:
                continue

            # 1. Deterministic Hard Rules with Scripting Guard
            if HardRuleEvaluator.has_hard_rules(quest):
                is_met, _ = HardRuleEvaluator.evaluate_hard_rules(
                    quest,
                    avatar,
                    state,
                    new_inventory_items=new_inventory_items,
                    new_scene_id=new_scene_id,
                    updated_entities=updated_entities,
                    script_context=script_context,
                )
                if is_met:
                    completed_ids.append(qid)
                continue

            if cls._check_soft_goal(avatar, state, quest):
                completed_ids.append(qid)

        return completed_ids

    @classmethod
    def _check_soft_goal(cls, avatar: Avatar, state: SessionState, quest: dict) -> bool:
        """Check equipment, collection, then travel heuristics for unstructured quests."""
        goal = quest.get("goal", "").lower()
        description = quest.get("description", "").lower()
        if ("equip" in goal or "equip" in description) and (
            cls._check_equipment_goal(avatar, goal)
            or cls._check_equipment_goal(avatar, description)
        ):
            return True
        if any(word in goal for word in ("collect", "find", "get")) and cls._check_inventory_goal(
            avatar, goal
        ):
            return True
        return any(
            word in goal for word in ("reach", "go to", "travel to")
        ) and cls._check_location_goal(state, goal)

    @staticmethod
    def _check_equipment_goal(avatar: Avatar, text: str) -> bool:
        """
        Checks if specific equipment slots are filled based on keywords in text.
        Example: "Equip items in the Head, Chest, and Hands slots"
        """
        slot_keywords = {
            "head": ("head",),
            "chest": ("chest",),
            "hands": ("hands",),
            "feet": ("feet",),
            "legs": ("legs",),
            "mainhand": ("mainhand", "main hand", "weapon"),
            "offhand": ("offhand", "off hand", "shield"),
            "neck": ("neck", "amulet", "necklace"),
        }
        slots_to_check = [
            slot
            for slot, keywords in slot_keywords.items()
            if any(word in text for word in keywords)
        ]
        if not slots_to_check:
            return False
        equipment = avatar.equipment or {}
        equipment_lower = {str(key).lower(): value for key, value in equipment.items()}
        return all(equipment_lower.get(slot) for slot in slots_to_check)

    @staticmethod
    def _check_inventory_goal(avatar: Avatar, text: str) -> bool:
        """
        Checks if specific items are in inventory.
        """
        inventory = avatar.inventory or []
        # Simple heuristic: extract nouns or specific item names
        # For now, we look for matches of item names in the text
        for item in inventory:
            iname = item.get("name", "").lower()
            if iname and iname in text:
                return True
        return False

    @staticmethod
    def _check_location_goal(_state: SessionState, _text: str) -> bool:
        """
        Checks if the current scene matches a target mentioned in the text.
        """
        # This requires knowing the scene label/name
        # current_scene_id is what we have.
        # We'd need to fetch the scene label to compare.
        # For now, return False until we have a better way to map ID to Name here.
        return False
