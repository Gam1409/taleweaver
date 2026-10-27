from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.game_modes import is_vn
from backend.engine.rule_engine import (
    GameEvent,
)
from backend.models.adventure_template import AdventureTemplate

logger = logging.getLogger(__name__)

CHECKPOINT_REASON_AWARD_GRANTED = "AWARD_GRANTED"


class TurnEventAwards:
    """Apply awards outcomes in the turn transaction."""

    async def _evaluate_deterministic_awards(
        self, event: GameEvent, script_context: Any = None
    ) -> list[str]:
        """Evaluates awards configured with deterministic hard rules and grants them if conditions are met."""
        from backend.engine.hard_rule_evaluator import HardRuleEvaluator

        if (
            is_vn(self.adventure)
            or not self.adventure
            or not self.adventure.awards
            or not self.user
        ):
            return []

        messages: list[str] = []
        user_awards = list(self.user.earned_awards or [])
        now = datetime.utcnow().isoformat()
        modified = False

        for aw in self.adventure.awards:
            if not isinstance(aw, dict) or not aw.get("key"):
                continue
            key = aw["key"]
            already_earned = any(
                ea.get("key") == key
                and (
                    ea.get("template_id") == self.adventure.id
                    or ea.get("adventure_id") == self.adventure.id
                )
                for ea in user_awards
            )
            if already_earned or not HardRuleEvaluator.has_hard_rules(aw):
                continue

            is_met, _ = HardRuleEvaluator.evaluate_hard_rules(
                aw,
                self.avatar,
                self.state,
                new_inventory_items=event.new_inventory_items,
                new_scene_id=event.new_scene_id,
                updated_entities=event.updated_entities,
                script_context=script_context,
            )
            if not is_met:
                continue

            user_awards.append(
                {
                    "key": key,
                    "title": aw.get("title") or key,
                    "description": aw.get("description"),
                    "tier": aw.get("tier"),
                    "template_id": self.adventure.id,
                    "adventure_id": self.adventure.id,
                    "adventure_title": self.adventure.title,
                    "session_id": self.state.session_id,
                    "earned_at": now,
                }
            )
            award_title = aw.get("title") or key
            msg = f"Award Achievement: {award_title}"
            await self._save_chat_message("system", msg)
            messages.append(msg)
            modified = True
            logger.info("[Turn %s] Deterministic Award Granted: %s", self.game_id, key)

        if modified:
            self.user.earned_awards = user_awards
            flag_modified(self.user, "earned_awards")
            self._queue_checkpoint(CHECKPOINT_REASON_AWARD_GRANTED)

        return messages

    async def _apply_award_keys(self, event, system_messages, vn_mode):
        if not (event.earned_award_keys and not vn_mode):
            return
        now = datetime.utcnow().isoformat()
        award_defs = {
            (aw.get("key") or ""): aw for aw in (self.adventure.awards or []) if aw.get("key")
        }
        user_awards = list(self.user.earned_awards or [])
        modified = False
        for key in event.earned_award_keys:
            if not key:
                continue
            already_earned = any(
                ea.get("key") == key
                and (
                    ea.get("template_id") == self.adventure.id
                    or ea.get("adventure_id") == self.adventure.id
                )
                for ea in user_awards
            )
            if already_earned:
                continue

            aw = award_defs.get(key)
            if not aw:
                logger.warning(
                    "[Turn %s] GM tried to grant non-existent award: %s", self.game_id, key
                )
                continue

            user_awards.append(
                {
                    "key": key,
                    "title": aw.get("title") or key,
                    "description": aw.get("description"),
                    "tier": aw.get("tier"),
                    "template_id": self.adventure.id,
                    "adventure_id": self.adventure.id,
                    "adventure_title": self.adventure.title,
                    "session_id": self.state.session_id,
                    "earned_at": now,
                }
            )
            award_title = aw.get("title") or key
            msg = f"Award Achievement: {award_title}"
            await self._save_chat_message("system", msg)
            system_messages.append(msg)
            modified = True

        if modified:
            self.user.earned_awards = user_awards
            flag_modified(self.user, "earned_awards")
            self._queue_checkpoint(CHECKPOINT_REASON_AWARD_GRANTED)

    async def _build_awards_payload(self, adventure: AdventureTemplate | None) -> list[dict]:
        """Helper to build the awards payload with earned status."""
        if is_vn(adventure or self.adventure) or not self.user:
            return []

        adv_id = adventure.id if adventure else (self.state.template_id if self.state else None)
        awards_list = (
            adventure.awards
            if adventure
            else (AdventureLogic.extract_manifest_snapshot(self.state).get("adventure") or {}).get(
                "awards"
            )
        ) or []
        session_id = self.state.session_id if self.state else None

        return AdventureLogic.build_awards_payload(
            user_earned_awards=self.user.earned_awards,
            adventure_awards=awards_list,
            adventure_id=adv_id,
            session_id=session_id,
        )
