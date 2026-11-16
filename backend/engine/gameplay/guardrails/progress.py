"""Progress guards: quest completion, awards and deterministic win/loss conditions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.core.state_rejection_trace import reject
from backend.engine.gameplay.guardrails.base import GuardrailBase
from backend.engine.hard_rule_evaluator import HardRuleEvaluator
from backend.engine.rule_engine import GameEvent
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


@dataclass
class Accessibility:
    """IDs and names (lower-cased) of everything the protagonist can reach this turn."""

    ids: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)

    def mark(self, ent_id: Any, name: Any) -> None:
        if ent_id:
            self.ids.add(str(ent_id).lower().strip())
        if name:
            self.names.add(str(name).lower().strip())

    def mark_items(self, items: Any) -> None:
        for item in items or []:
            if isinstance(item, dict):
                self.mark(item.get("id"), item.get("name"))

    def reaches(self, ent: WorldEntity) -> bool:
        return bool(
            (ent.id and ent.id.lower().strip() in self.ids)
            or (ent.name and ent.name.lower().strip() in self.names)
        )


def _mentions(text_lower: str, ent: WorldEntity) -> bool:
    """Word-boundary match so e.g. 'key' does not match 'keyboard'."""
    return any(
        token and re.search(r"\b" + re.escape(token.lower()) + r"\b", text_lower)
        for token in (ent.id, ent.name)
    )


class ProgressGuardMixin(GuardrailBase):
    """Blocks quest/award grants that depend on unreachable entities or unmet hard rules."""

    def _accessibility(self, event: GameEvent, entities: list[WorldEntity]) -> Accessibility:
        acc = Accessibility()
        scene = self.state.current_scene_id
        for ent in entities:
            if ent.current_scene_id == scene:
                acc.mark(ent.id, ent.name)
                if ent.entity_type == "NPC":
                    acc.mark_items(ent.inventory)
            if ent.is_in_inventory:
                acc.mark(ent.id, ent.name)
        acc.mark_items(self.avatar.inventory)
        acc.mark_items(list((self.avatar.equipment or {}).values()))
        for item in [*(event.new_inventory_items or []), *(event.spawned_items or [])]:
            acc.mark(item.id, item.name)
        by_id = {e.id: e for e in entities}
        for move in event.moved_entities or []:
            if move.to_scene_id == scene:
                moved = by_id.get(move.entity_id)
                acc.mark(move.entity_id, moved.name if moved else None)
        return acc

    @staticmethod
    def _depends_on_unreachable(
        texts: list[Any], entities: list[WorldEntity], acc: Accessibility
    ) -> bool:
        for text in texts:
            if not text:
                continue
            lowered = str(text).lower()
            blocker = next(
                (
                    e
                    for e in entities
                    if (e.id or e.name) and _mentions(lowered, e) and not acc.reaches(e)
                ),
                None,
            )
            if blocker is not None:
                logger.info(
                    "[Quest/Award Guardrail] Blocked because text '%s' mentions inaccessible entity '%s' (%s)",
                    text,
                    blocker.name or "",
                    blocker.id or "",
                )
                return True
        return False

    def _hard_rules_unmet(self, rule_owner: dict[str, Any], event: GameEvent) -> str | None:
        if not HardRuleEvaluator.has_hard_rules(rule_owner):
            return None
        is_met, reason = HardRuleEvaluator.evaluate_hard_rules(
            rule_owner,
            self.avatar,
            self.state,
            new_inventory_items=event.new_inventory_items,
            new_scene_id=event.new_scene_id,
            updated_entities=event.updated_entities,
        )
        return None if is_met else (reason or "unmet hard rule")

    def _validated(
        self,
        keys: list[str],
        lookup: dict[str, dict[str, Any]],
        text_fields: tuple[str, str],
        label: str,
        context: tuple[GameEvent, list[WorldEntity], Accessibility],
    ) -> list[str]:
        event, entities, acc = context
        kept = []
        for key in keys:
            owner = lookup.get(key)
            if owner is None:
                kept.append(key)
                continue
            unmet = self._hard_rules_unmet(owner, event)
            if unmet:
                reject(
                    "progression",
                    "unmet_hard_rule",
                    unmet,
                    proposal=key,
                    target_id=key,
                    reward_type=label,
                    rule_owner=owner,
                    event=event,
                    current_scene_id=self.state.current_scene_id,
                    current_inventory=self.avatar.inventory,
                    current_equipment=self.avatar.equipment,
                )
                logger.info(
                    "[%s Guardrail] Blocked '%s' due to unmet hard rule: %s", label, key, unmet
                )
                continue
            if self._depends_on_unreachable([owner.get(f) for f in text_fields], entities, acc):
                reject(
                    "progression",
                    "inaccessible_dependency",
                    "The proposed quest completion or award depends on an entity the protagonist cannot currently reach.",
                    proposal=key,
                    target_id=key,
                    reward_type=label,
                    rule_owner=owner,
                    event=event,
                    current_scene_id=self.state.current_scene_id,
                    accessible_entity_ids=acc.ids,
                    entities=[
                        {
                            "id": entity.id,
                            "name": entity.name,
                            "current_scene_id": entity.current_scene_id,
                        }
                        for entity in entities
                    ],
                )
                logger.info(
                    "[%s Guardrail] Blocked '%s' due to inaccessible entity dependency.", label, key
                )
                continue
            kept.append(key)
        return kept

    async def _enforce_quest_and_award_guardrails(self, event: GameEvent) -> None:
        """Drops quest completions/awards whose hard rules are unmet or that need unreachable entities."""
        if not event.completed_quest_ids and not event.earned_award_keys:
            return
        entities = await self._session_entities()
        context = (event, entities, self._accessibility(event, entities))
        if event.completed_quest_ids:
            quests = {
                q["id"]: q
                for q in reversed(self.state.quests or [])
                if isinstance(q.get("id"), str)
            }
            event.completed_quest_ids = self._validated(
                event.completed_quest_ids, quests, ("goal", "description"), "Quest", context
            )
        if event.earned_award_keys:
            awards = {
                a["key"]: a
                for a in reversed((self.adventure.awards if self.adventure else []) or [])
                if isinstance(a.get("key"), str)
            }
            event.earned_award_keys = self._validated(
                event.earned_award_keys, awards, ("requirement", "description"), "Award", context
            )

    def _guard_expression(self, field_name: str) -> str:
        adventure = getattr(self.manager, "adventure", None)
        raw = getattr(self.state, field_name, None) or (
            getattr(adventure, field_name, None) if adventure else None
        )
        return raw.strip() if isinstance(raw, str) else ""

    def _apply_loss_guard(
        self, event: GameEvent, script_context: Any, violations: list[str]
    ) -> None:
        guard = self._guard_expression("gameover_guard_expression")
        if not guard:
            return
        met, reason = HardRuleEvaluator.check_guard_expression(
            guard, self.avatar, self.state, script_context=script_context
        )
        if met:
            event.game_over = True
            if not event.status_note:
                condition = (
                    getattr(self.state, "gameover_condition", None) or "Defeat condition triggered."
                )
                event.status_note = f"Defeat condition met: {condition}"
            return
        if event.game_over and (getattr(self.avatar, "hp", 100) or 100) > 0:
            reject(
                "progression",
                "loss_guard_unmet",
                reason or "The loss guard expression was not satisfied.",
                proposal={"game_over": event.game_over, "status_note": event.status_note},
                guard_expression=guard,
                current_hp=getattr(self.avatar, "hp", 100),
                current_scene_id=self.state.current_scene_id,
            )
            logger.info(
                "[Loss Guardrail] Blocked game_over: guard expression '%s' not satisfied (%s)",
                guard,
                reason,
            )
            event.game_over = False
            event.status_note = None
            violations.append(f"Blocked game over: guard expression '{guard}' not met.")

    def _apply_win_guard(
        self, event: GameEvent, script_context: Any, violations: list[str]
    ) -> None:
        guard = self._guard_expression("completed_guard_expression")
        if not guard:
            return
        met, reason = HardRuleEvaluator.check_guard_expression(
            guard, self.avatar, self.state, script_context=script_context
        )
        if met:
            event.game_completed = True
            if not event.status_note:
                condition = getattr(self.state, "completed_condition", None) or "Victory achieved!"
                event.status_note = f"Victory condition met: {condition}"
            return
        if event.game_completed:
            reject(
                "progression",
                "win_guard_unmet",
                reason or "The completion guard expression was not satisfied.",
                proposal={"game_completed": event.game_completed, "status_note": event.status_note},
                guard_expression=guard,
                current_hp=getattr(self.avatar, "hp", 100),
                current_scene_id=self.state.current_scene_id,
            )
            logger.info(
                "[Win Guardrail] Blocked game_completed: guard expression '%s' not satisfied (%s)",
                guard,
                reason,
            )
            event.game_completed = False
            event.status_note = None
            violations.append(f"Blocked game completion: guard expression '{guard}' not met.")

    async def _enforce_win_and_loss_guardrails(
        self, event: GameEvent, script_context: Optional[Any] = None
    ) -> list[str]:
        """Triggers win/loss deterministically when guards are met and blocks hallucinated outcomes when not."""
        violations: list[str] = []
        self._apply_loss_guard(event, script_context, violations)
        self._apply_win_guard(event, script_context, violations)
        return violations
