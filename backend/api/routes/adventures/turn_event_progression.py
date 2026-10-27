from __future__ import annotations

import logging
from copy import deepcopy

from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.quest_manager import QuestManager
from backend.models.chat import ChatMessage

logger = logging.getLogger(__name__)

CHECKPOINT_REASON_QUEST_UPDATE = "QUEST_UPDATE"


class TurnEventProgression:
    """Apply progression outcomes in the turn transaction."""

    async def _apply_explicit_progression(self, event, system_messages, vn_mode):
        state_dirty = False
        # Quest Updates
        newly_completed_quests: list[dict] = []
        if event.completed_quest_ids and not vn_mode:
            new_quests = deepcopy(self.state.quests or [])
            modified = False
            for qid in event.completed_quest_ids:
                for q in new_quests:
                    if q.get("id") == qid and q.get("status") != "completed":
                        q["status"] = "completed"
                        newly_completed_quests.append(q)
                        modified = True

            if modified:
                self.state.quests = new_quests
                state_dirty = True

        await self._apply_award_keys(event, system_messages, vn_mode)

        return state_dirty, newly_completed_quests

    async def _apply_deterministic_quests(
        self, event, system_messages, vn_mode, script_context, newly_completed_quests
    ):
        state_dirty = False
        # Deterministic Quest Sync (Post-LLM check)
        det_completed = (
            []
            if vn_mode
            else QuestManager.evaluate_quests(
                self.avatar,
                self.state,
                new_inventory_items=event.new_inventory_items,
                new_scene_id=event.new_scene_id,
                updated_entities=event.updated_entities,
                script_context=script_context,
            )
        )
        if det_completed:
            new_quests = deepcopy(self.state.quests or [])
            modified = False
            for qid in det_completed:
                for q in new_quests:
                    if q.get("id") == qid and q.get("status") != "completed":
                        q["status"] = "completed"
                        if not any(nq.get("id") == qid for nq in newly_completed_quests):
                            newly_completed_quests.append(q)
                        logger.info(
                            "[Turn %s] Deterministic Quest Completion: %s", self.game_id, qid
                        )
                        modified = True
            if modified:
                self.state.quests = new_quests
                state_dirty = True

        if newly_completed_quests:
            self._queue_checkpoint(CHECKPOINT_REASON_QUEST_UPDATE)
            # Emit one system entry per newly completed quest so players get explicit feedback.
            for q in newly_completed_quests:
                quest_title = q.get("title") or q.get("id")
                xp_reward = int(q.get("exp_reward") or 0)
                if xp_reward > 0:
                    self.avatar.exp = (self.avatar.exp or 0) + xp_reward
                    msg = f"Side-quest completed: {quest_title} (+{xp_reward} XP)"
                else:
                    msg = f"Side-quest completed: {quest_title}"
                self.db.add(
                    ChatMessage(
                        session_id=self.state.session_id,
                        role="system",
                        content=msg,
                    )
                )
                system_messages.append(msg)

        return state_dirty

    async def _apply_sequence_progression(self, event, system_messages, vn_mode, script_context):
        state_dirty = False
        # Sequence Completion Logic
        old_seq_id = self.state.active_sequence_id
        seq_messages = (
            []
            if vn_mode
            else AdventureLogic.evaluate_sequence_progress(
                adventure=self.adventure,
                state=self.state,
                avatar=self.avatar,
                new_inventory_items=event.new_inventory_items,
                new_scene_id=event.new_scene_id,
                updated_entities=event.updated_entities,
                force_complete=bool(event.sequence_completed),
                script_context=script_context,
            )
        )
        event.sequence_completed = bool(seq_messages)
        if seq_messages:
            state_dirty = True
            for seq_msg in seq_messages:
                await self._save_chat_message("system", seq_msg)
                system_messages.append(seq_msg)
            await self._fire_sequence_hooks(old_seq_id, system_messages)
            if getattr(self.state, "is_completed", False):
                event.game_completed = True
                if not event.status_note:
                    event.status_note = "Congratulations! You have completed the final sequence."

        await self._apply_win_guard(event, vn_mode, script_context)

        return state_dirty

    async def _apply_win_guard(self, event, vn_mode, script_context):
        raw_win_guard = getattr(self.state, "completed_guard_expression", None) or getattr(
            self.adventure, "completed_guard_expression", None
        )
        win_guard = raw_win_guard.strip() if isinstance(raw_win_guard, str) else ""

        if win_guard and not vn_mode:
            from backend.engine.hard_rule_evaluator import HardRuleEvaluator

            is_win_met, _ = HardRuleEvaluator.check_guard_expression(
                win_guard, self.avatar, self.state, script_context=script_context
            )
            if is_win_met:
                event.game_completed = True
                if not event.status_note:
                    event.status_note = "Congratulations! You have achieved victory."
            elif event.game_completed:
                event.game_completed = False

    async def _fire_sequence_hooks(self, old_seq_id, system_messages):
        sequences = sorted(
            getattr(self.adventure, "sequences", None) or [], key=lambda x: x.get("order", 1)
        )
        completed_seq = next((s for s in sequences if s.get("id") == old_seq_id), None)
        if completed_seq:
            if completed_seq.get("on_end_sequence_script"):
                end_msgs = await self.manager._execute_inline_script(
                    completed_seq["on_end_sequence_script"],
                    "on_end_sequence",
                    completed_seq.get("id"),
                )
                system_messages.extend(end_msgs)
            if completed_seq.get("on_end_sequence_text"):
                await self._save_chat_message("system", completed_seq["on_end_sequence_text"])
                system_messages.append(completed_seq["on_end_sequence_text"])
        new_seq = next((s for s in sequences if s.get("id") == self.state.active_sequence_id), None)
        if new_seq and new_seq != completed_seq:
            if new_seq.get("on_start_sequence_script"):
                start_msgs = await self.manager._execute_inline_script(
                    new_seq["on_start_sequence_script"], "on_start_sequence", new_seq.get("id")
                )
                system_messages.extend(start_msgs)
            if new_seq.get("on_start_sequence_text"):
                await self._save_chat_message("system", new_seq["on_start_sequence_text"])
                system_messages.append(new_seq["on_start_sequence_text"])

    async def _progression_script_context(
        self,
    ):
        script_context = None
        if hasattr(self, "manager") and hasattr(self.manager, "_build_script_context"):
            try:
                script_context = await self.manager._build_script_context()
            except Exception as exc:
                logger.warning("Could not build script context for progression evaluation: %s", exc)

        return script_context
