from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.engine.rule_engine import (
    RuleEngine,
)
from backend.engine.visual_novel.time import apply_elapsed_time
from backend.engine.world_memory_notifications import memory_saved_message, notification_language
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


class TurnEventWorld:
    """Apply world outcomes in the turn transaction."""

    async def _apply_avatar_outcomes(self, event, system_messages):
        if event.new_status_effects:
            for effect in event.new_status_effects:
                msg = f"You are now: {effect}"
                await self._save_chat_message("system", msg)
                system_messages.append(msg)

        old_hp = self.avatar.hp
        old_status = list(self.avatar.status_effects or [])
        RuleEngine.apply_event(self.avatar, event)
        prot_meta = getattr(self.avatar, "stats", None) or {}
        if self.avatar.hp != old_hp:
            if prot_meta.get("on_hp_change_script"):
                msgs = await self.manager._execute_inline_script(
                    prot_meta["on_hp_change_script"], "on_hp_change", "protagonist"
                )
                system_messages.extend(msgs)
            if prot_meta.get("on_hp_change_text"):
                await self._save_chat_message("system", prot_meta["on_hp_change_text"])
                system_messages.append(prot_meta["on_hp_change_text"])
        if list(self.avatar.status_effects or []) != old_status:
            if prot_meta.get("on_status_change_script"):
                msgs = await self.manager._execute_inline_script(
                    prot_meta["on_status_change_script"], "on_status_change", "protagonist"
                )
                system_messages.extend(msgs)
            if prot_meta.get("on_status_change_text"):
                await self._save_chat_message("system", prot_meta["on_status_change_text"])
                system_messages.append(prot_meta["on_status_change_text"])

    async def _synchronize_npc_inventories(self, states):
        state_dirty = False
        # Auto-cleanup: remove items from NPC inventories if they are now in the scene or player inventory
        player_item_ids = {
            item.get("id")
            for item in (self.avatar.inventory or [])
            if isinstance(item, dict) and item.get("id")
        }
        obj_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id, WorldEntity.entity_type == "OBJECT"
            )
        )
        all_objs = obj_res.scalars().all()
        spawned_or_player_ids = set(player_item_ids)
        for obj in all_objs:
            is_in_inv = states.get(obj.id, {}).get("is_in_inventory", obj.is_in_inventory)
            if not is_in_inv:
                # Only add objects that are in the scene (not in any inventory).
                # Objects with is_in_inventory=True may belong to NPC inventories and
                # must NOT be added here, otherwise the cleanup loop below would
                # incorrectly strip them from every NPC's inventory.
                spawned_or_player_ids.add(obj.id)

        npc_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id, WorldEntity.entity_type == "NPC"
            )
        )
        all_npcs = npc_res.scalars().all()
        for npc in all_npcs:
            npc_inv = states.get(npc.id, {}).get("inventory", npc.inventory)
            if npc_inv and isinstance(npc_inv, list):
                cleaned_inv = []
                npc_inv_modified = False
                for item in npc_inv:
                    if isinstance(item, dict):
                        item_id = item.get("id")
                        if item_id and item_id in spawned_or_player_ids:
                            logger.info(
                                "[Turn %s] Removing item %s from NPC %s inventory during auto-sync cleanup.",
                                self.game_id,
                                item_id,
                                npc.id,
                            )
                            npc_inv_modified = True
                            continue
                    cleaned_inv.append(item)

                if npc_inv_modified:
                    if npc.id not in states:
                        states[npc.id] = {}
                    states[npc.id]["inventory"] = cleaned_inv
                    state_dirty = True

        return state_dirty

    async def _apply_world_memories(self, event, system_messages):
        if not (event.new_world_memories):
            return
        import uuid

        memory_language = await notification_language(self.manager)
        existing_memories = list(self.state.world_memories or [])
        for mem in event.new_world_memories:
            target_scene_id = mem.scene_id or (self.state.current_scene_id if self.state else None)
            # Deduplication check: prevent identical memories in the same scene/scope
            is_duplicate = any(
                (m.get("description") or "").strip().lower()
                == (mem.description or "").strip().lower()
                and (m.get("scope") == mem.scope)
                and (mem.scope == "global" or (m.get("scene_id") or "") == (target_scene_id or ""))
                for m in existing_memories
            )
            if is_duplicate:
                logger.info(
                    "[Turn %s] Skipping duplicate world memory: %s",
                    self.game_id,
                    mem.description,
                )
                continue

            new_mem = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "description": mem.description,
                "npc_id": mem.npc_id,
                "emotion": mem.emotion,
                "scope": mem.scope,
                "scene_id": target_scene_id,
            }
            existing_memories.append(new_mem)
            msg = memory_saved_message(mem.description, mem.scope, mem.emotion, memory_language)
            await self._save_chat_message("system", msg)
            system_messages.append(msg)
        self.state.world_memories = existing_memories
        flag_modified(self.state, "world_memories")
        self._queue_checkpoint("world_memories_updated")
        event.new_world_memories = None

    async def _apply_turn_time(self, event, vn_mode):
        state_dirty = False
        # Time Management
        if event.start_datetime_override:
            self.state.start_datetime = event.start_datetime_override
            state_dirty = True

        if vn_mode:
            state_dirty = apply_elapsed_time(self.state, event, self.adventure) or state_dirty
        elif event.time_override_minutes is not None:
            self.state.in_game_time = max(0, int(event.time_override_minutes))
            state_dirty = True
        elif event.extra_time_minutes != 0:
            base_turn = int(
                self.adventure.time_per_turn if self.adventure.time_per_turn is not None else 5
            )
            max_turn = getattr(self.adventure, "max_time_per_turn", None)
            if max_turn is None and self.adventure.time_config:
                max_turn = self.adventure.time_config.get("max_time_per_turn")

            extra = int(event.extra_time_minutes)
            if max_turn is not None and max_turn > 0:
                total_turn_time = max(0, min(base_turn + extra, max_turn))
                delta_to_add = total_turn_time - base_turn
            else:
                total_turn_time = max(0, base_turn + extra)
                delta_to_add = total_turn_time - base_turn

            if delta_to_add != 0:
                self.state.in_game_time = max(0, self.state.in_game_time + delta_to_add)
                state_dirty = True

        return state_dirty
