from __future__ import annotations

import logging

from sqlalchemy import select

from backend.models.world_entity import WorldEntity, WorldScene

logger = logging.getLogger(__name__)


class TurnEventEntities:
    """Apply entities outcomes in the turn transaction."""

    async def _apply_entity_movements(self, event, states, system_messages):
        state_dirty = False
        if not (event.moved_entities):
            return False
        for move in event.moved_entities:
            eid = move.entity_id
            if eid not in states:
                states[eid] = {}
            if move.to_scene_id:
                states[eid]["current_scene_id"] = move.to_scene_id
                # If moving to a new scene, clear spatial position unless a new one is provided
                if not move.to_spatial_position:
                    states[eid]["spatial_position"] = None

                # Emit system message for NPC movement
                ent_name = eid
                ent_res = await self.db.execute(
                    select(WorldEntity).where(
                        WorldEntity.id == eid, WorldEntity.session_id == self.game_id
                    )
                )
                ent_obj = ent_res.scalars().first()
                if ent_obj:
                    ent_name = ent_obj.name
                scene_label = move.to_scene_id
                scene_res = await self.db.execute(
                    select(WorldScene).where(
                        WorldScene.id == move.to_scene_id, WorldScene.session_id == self.game_id
                    )
                )
                scene_obj = scene_res.scalars().first()
                if scene_obj:
                    scene_label = scene_obj.label
                msg = f"{ent_name} moved to {scene_label}."
                await self._save_chat_message("system", msg)
                system_messages.append(msg)

            if move.to_spatial_position:
                states[eid]["spatial_position"] = move.to_spatial_position
            state_dirty = True

        return state_dirty

    async def _apply_entity_updates(self, event, states, system_messages, vn_mode):
        state_dirty = False
        if not (event.updated_entities):
            return False
        for update in event.updated_entities:
            eid = update.entity_id
            ent_obj = None
            if eid not in states:
                states[eid] = {}
            await self._apply_entity_description(update, states, eid)

            await self._apply_entity_attributes(update, states, eid)

            ent_obj = await self._apply_entity_defeat(update, states, eid, system_messages, vn_mode)

            await self._apply_entity_unlock(update, states, eid, ent_obj, system_messages, vn_mode)

            if update.inventory is not None:
                states[eid]["inventory"] = [
                    i.model_dump(exclude_none=True) for i in update.inventory
                ]
            state_dirty = True

        return state_dirty

    async def _apply_entity_description(self, update, states, eid):
        if update.name is not None:
            states[eid]["name"] = update.name
        if update.description is not None:
            states[eid]["description"] = update.description
        if update.spatial_position is not None:
            states[eid]["spatial_position"] = update.spatial_position
        if update.is_hidden is not None:
            states[eid]["is_hidden"] = update.is_hidden

    async def _apply_entity_attributes(self, update, states, eid):
        if update.hp is not None:
            states[eid]["hp"] = update.hp
        if update.mana is not None:
            states[eid]["mana"] = update.mana
        if update.stamina is not None:
            states[eid]["stamina"] = update.stamina
        if update.is_attackable is not None:
            states[eid]["is_attackable"] = update.is_attackable
        if update.is_killable is not None:
            states[eid]["is_killable"] = update.is_killable
        if update.switch_state is not None:
            states[eid]["switch_state"] = update.switch_state
        if update.notes is not None:
            states[eid]["notes"] = update.notes
        if update.moveable is not None:
            states[eid]["moveable"] = update.moveable
        if update.allowed_scenes is not None:
            states[eid]["allowed_scenes"] = update.allowed_scenes

    async def _apply_entity_defeat(self, update, states, eid, system_messages, vn_mode):
        ent_obj = None
        if not (update.is_defeated is not None and not vn_mode):
            return None
        was_defeated = self.state.entity_states.get(eid, {}).get("is_defeated", False)
        if not was_defeated and update.is_defeated is True:
            ent_res = await self.db.execute(
                select(WorldEntity).where(
                    WorldEntity.id == eid,
                    WorldEntity.session_id == self.game_id,
                )
            )
            ent_obj = ent_res.scalars().first()
            if ent_obj and ent_obj.entity_type == "NPC":
                xp_gained = self._award_combat_victory_xp(ent_obj)
                msg = f"Defeated {ent_obj.name}!"
                xp_msg = f"you gained {xp_gained} XP"
                await self._save_chat_message("system", msg)
                await self._save_chat_message("system", xp_msg)
                system_messages.append(msg)
                system_messages.append(xp_msg)

                npc_meta = dict(ent_obj.metadata_json or {})
                if npc_meta.get("on_defeat_script"):
                    msgs = await self.manager._execute_inline_script(
                        npc_meta["on_defeat_script"], "on_defeat", ent_obj.id
                    )
                    system_messages.extend(msgs)
                if npc_meta.get("on_defeat_text"):
                    await self._save_chat_message("system", npc_meta["on_defeat_text"])
                    system_messages.append(npc_meta["on_defeat_text"])
        states[eid]["is_defeated"] = update.is_defeated
        return ent_obj

    async def _apply_entity_unlock(self, update, states, eid, ent_obj, system_messages, vn_mode):
        if not (update.locked is not None):
            return
        was_locked = self.state.entity_states.get(eid, {}).get("locked")
        if was_locked is None:
            ent_res = await self.db.execute(
                select(WorldEntity).where(
                    WorldEntity.id == eid,
                    WorldEntity.session_id == self.game_id,
                )
            )
            ent_obj = ent_res.scalars().first()
            if ent_obj:
                metadata_json = dict(ent_obj.metadata_json or {})
                was_locked = bool(
                    metadata_json.get("code_to_unlock")
                    or metadata_json.get("item_to_unlock")
                    or metadata_json.get("rule_to_unlock")
                )

        if was_locked and update.locked is False:
            if ent_obj is None:
                ent_res = await self.db.execute(
                    select(WorldEntity).where(
                        WorldEntity.id == eid,
                        WorldEntity.session_id == self.game_id,
                    )
                )
                ent_obj = ent_res.scalars().first()

            await self._fire_container_unlock(ent_obj, system_messages, vn_mode)

        states[eid]["locked"] = update.locked

    async def _fire_container_unlock(self, ent_obj, system_messages, vn_mode):
        if (
            ent_obj
            and ent_obj.entity_type == "OBJECT"
            and str(ent_obj.item_type or "").upper() == "CONTAINER"
        ):
            metadata_json = dict(ent_obj.metadata_json or {})
            code_to_unlock = str(metadata_json.get("code_to_unlock") or "").strip()
            if code_to_unlock and not vn_mode:
                xp_reward = metadata_json.get("exp_reward") or metadata_json.get("xp_reward") or 100
                self.avatar.exp = (self.avatar.exp or 0) + xp_reward
                msg = f"Unlocked {ent_obj.name} with the correct code!"
                xp_msg = f"you gained {xp_reward} XP"
                await self._save_chat_message("system", msg)
                await self._save_chat_message("system", xp_msg)
                system_messages.append(msg)
                system_messages.append(xp_msg)
            else:
                msg = f"Container unlocked: {ent_obj.name}."
                await self._save_chat_message("system", msg)
                system_messages.append(msg)

            if metadata_json.get("on_unlock_success_script"):
                msgs = await self.manager._execute_inline_script(
                    metadata_json["on_unlock_success_script"],
                    "on_unlock_success",
                    ent_obj.id,
                )
                system_messages.extend(msgs)
            if metadata_json.get("on_unlock_success_text"):
                await self._save_chat_message("system", metadata_json["on_unlock_success_text"])
                system_messages.append(metadata_json["on_unlock_success_text"])
