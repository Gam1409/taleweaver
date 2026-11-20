"""Progress guards: quest completion, awards and deterministic win/loss conditions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.core.state_rejection_trace import reject
from backend.engine.gameplay.guardrails.base import GuardrailBase, entity_view
from backend.engine.hard_rule_evaluator import HardRuleEvaluator
from backend.engine.rule_engine import GameEvent
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


@dataclass
class Accessibility:
    """Canonical IDs reachable in the proposed turn."""

    ids: set[str] = field(default_factory=set)

    def mark(self, entity_id: str | None) -> None:
        if entity_id:
            self.ids.add(entity_id.strip().casefold())

    def mark_items(self, items: Any) -> None:
        for item in items or []:
            if isinstance(item, dict):
                self.mark(item.get("id"))
            elif isinstance(item, str):
                self.mark(item)


class ProgressGuardMixin(GuardrailBase):
    """Blocks quest/award grants that depend on unreachable entities or unmet hard rules."""

    def _accessibility(self, event: GameEvent, entities: list[WorldEntity]) -> Accessibility:
        acc = Accessibility()
        scene = self.state.current_scene_id
        movements = {move.entity_id: move.to_scene_id for move in event.moved_entities or []}
        visibility = {
            change.entity_id: change.is_hidden
            for change in event.updated_entities or []
            if change.is_hidden is not None
        }
        for ent in entities:
            view = entity_view(ent, self.state.entity_states or {})
            present = movements.get(ent.id, view.scene_id) == scene and not visibility.get(
                ent.id, view.hidden
            )
            if present or view.in_inventory:
                acc.mark(ent.id)
            if present and ent.entity_type == "NPC":
                override = (self.state.entity_states or {}).get(ent.id, {})
                acc.mark_items(override.get("inventory", ent.inventory))
        acc.mark_items(self.avatar.inventory)
        acc.mark_items(list((self.avatar.equipment or {}).values()))
        for item in [*(event.new_inventory_items or []), *(event.spawned_items or [])]:
            acc.mark(item.id)
        return acc

    @staticmethod
    def _depends_on_unreachable(
        requirement: str, entities: list[WorldEntity], acc: Accessibility
    ) -> bool:
        # Legacy authors embedded canonical ID tokens directly in the objective.
        # Only uppercase technical tokens carry this meaning; display names and
        # incidental mentions in descriptions cannot add a prerequisite.
        ids = set(re.findall(r"(?<![\w-])[A-Z][A-Z0-9_-]*(?![\w-])", requirement))
        return any(ent.id in ids and ent.id.casefold() not in acc.ids for ent in entities)

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
        objective_field: str,
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
            if not HardRuleEvaluator.has_hard_rules(owner) and self._depends_on_unreachable(
                str(owner.get(objective_field) or ""), entities, acc
            ):
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
                event.completed_quest_ids, quests, "goal", "Quest", context
            )
        if event.earned_award_keys:
            awards = {
                a["key"]: a
                for a in reversed((self.adventure.awards if self.adventure else []) or [])
                if isinstance(a.get("key"), str)
            }
            event.earned_award_keys = self._validated(
                event.earned_award_keys, awards, "requirement", "Award", context
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
