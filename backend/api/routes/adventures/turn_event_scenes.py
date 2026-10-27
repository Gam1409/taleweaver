from __future__ import annotations

import logging

from sqlalchemy import and_, or_, select

from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.map_engine import MapEngine
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene

logger = logging.getLogger(__name__)

CHECKPOINT_REASON_SCENE_CHANGE = "SCENE_CHANGE"


class TurnEventScenes:
    """Apply scenes outcomes in the turn transaction."""

    async def _apply_scene_transition(self, event, states, system_messages):
        state_dirty = False
        if event.new_scene_id and event.new_scene_id != self.state.current_scene_id:
            # Enforce that the target scene is adjacent (connected by a WorldExit from the current scene)
            exit_res = await self.db.execute(
                select(WorldExit).where(
                    WorldExit.session_id == self.state.session_id,
                    or_(
                        and_(
                            WorldExit.from_scene_id == self.state.current_scene_id,
                            WorldExit.to_scene_id == event.new_scene_id,
                        ),
                        and_(
                            WorldExit.from_scene_id == event.new_scene_id,
                            WorldExit.to_scene_id == self.state.current_scene_id,
                            WorldExit.exit_type == "bidirectional",
                        ),
                    ),
                )
            )
            valid_exit = exit_res.scalars().first()
            if not valid_exit:
                blocked_msg = f"Movement blocked: The destination '{event.new_scene_id}' is not adjacent to your current location."
                await self._save_chat_message("system", blocked_msg)
                system_messages.append(blocked_msg)

                logger.warning(
                    f"[Turn {self.game_id}] Blocked invalid/non-adjacent scene transition: "
                    f"{self.state.current_scene_id} -> {event.new_scene_id}"
                )
                event.new_scene_id = None
                event.scene_label = None
                event.exit_label = None
            else:
                old_scene_id = await self._leave_previous_scene(system_messages)

                self.state.current_scene_id = event.new_scene_id
                state_dirty = True

                await self._register_scene_arrival(
                    event, states, system_messages, old_scene_id, valid_exit
                )

        return state_dirty

    async def _leave_previous_scene(self, system_messages):
        old_scene_id = self.state.current_scene_id
        if not (old_scene_id):
            return old_scene_id
        old_sc_res = await self.db.execute(
            select(WorldScene).where(
                WorldScene.id == old_scene_id,
                WorldScene.session_id == self.state.session_id,
            )
        )
        old_sc_db = old_sc_res.scalars().first()
        if old_sc_db:
            if old_sc_db.on_leave_scene_script:
                msgs = await self.manager._execute_inline_script(
                    old_sc_db.on_leave_scene_script, "on_leave_scene", old_sc_db.id
                )
                system_messages.extend(msgs)
            if old_sc_db.on_leave_scene_text:
                await self._save_chat_message("system", old_sc_db.on_leave_scene_text)
                system_messages.append(old_sc_db.on_leave_scene_text)

        return old_scene_id

    async def _register_scene_arrival(
        self, event, states, system_messages, old_scene_id, valid_exit
    ):
        # Map Update
        try:
            world_map = await AdventureLogic.get_or_create_map(self.db, self.state.template_id)
            # 1. Register exit between scenes
            MapEngine.register_exit(
                world_map,
                old_scene_id,
                event.new_scene_id,
                exit_label=event.exit_label or "",
                exit_type=valid_exit.exit_type if valid_exit else "one_way",
            )
            # 2. Register visit to the new scene
            # Use session snapshot for scene data
            scene_res = await self.db.execute(
                select(WorldScene).where(
                    WorldScene.id == event.new_scene_id,
                    WorldScene.session_id == self.state.session_id,
                )
            )
            new_scene_db = scene_res.scalars().first()

            # Add system message for scene change
            scene_name = (
                new_scene_db.label if new_scene_db else (event.scene_label or "a new location")
            )
            msg = f"You have entered: {scene_name}"
            await self._save_chat_message("system", msg)
            system_messages.append(msg)
            self._queue_checkpoint(CHECKPOINT_REASON_SCENE_CHANGE, scene_label=scene_name)

            await self._fire_arrival_hooks(event, states, system_messages, valid_exit, new_scene_db)

            MapEngine.register_visit(
                world_map,
                event.new_scene_id,
                label=new_scene_db.label if new_scene_db else event.scene_label,
                description=new_scene_db.description if new_scene_db else None,
                image_url=new_scene_db.image_url if new_scene_db else None,
            )
        except Exception as e:
            logger.error(f"Map update failed during turn: {e}")

    async def _fire_arrival_hooks(self, event, states, system_messages, valid_exit, new_scene_db):
        # Trigger on_open_exit and on_exit_used if applicable
        if valid_exit:
            if valid_exit.on_open_exit_script:
                msgs = await self.manager._execute_inline_script(
                    valid_exit.on_open_exit_script, "on_open_exit", valid_exit.id
                )
                system_messages.extend(msgs)
            if valid_exit.on_open_exit_text:
                await self._save_chat_message("system", valid_exit.on_open_exit_text)
                system_messages.append(valid_exit.on_open_exit_text)
            if getattr(valid_exit, "on_exit_used_script", None):
                msgs = await self.manager._execute_inline_script(
                    valid_exit.on_exit_used_script, "on_exit_used", valid_exit.id
                )
                system_messages.extend(msgs)
            if getattr(valid_exit, "on_exit_used_text", None):
                await self._save_chat_message("system", valid_exit.on_exit_used_text)
                system_messages.append(valid_exit.on_exit_used_text)

        if new_scene_db and new_scene_db.on_enter_scene_script:
            msgs = await self.manager._execute_inline_script(
                new_scene_db.on_enter_scene_script, "on_enter_scene", new_scene_db.id
            )
            system_messages.extend(msgs)
        if new_scene_db and new_scene_db.on_enter_scene_text:
            await self._save_chat_message("system", new_scene_db.on_enter_scene_text)
            system_messages.append(new_scene_db.on_enter_scene_text)

        await self._fire_npc_arrival_hooks(event, states, system_messages)

    async def _fire_npc_arrival_hooks(self, event, states, system_messages):
        # Check for NPCs in the new scene and run their hooks
        npc_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id, WorldEntity.entity_type == "NPC"
            )
        )
        all_npcs = npc_res.scalars().all()
        for npc in all_npcs:
            npc_scene = states.get(npc.id, {}).get("current_scene_id", npc.current_scene_id)
            if npc_scene == event.new_scene_id:
                npc_meta = dict(npc.metadata_json or {})
                if npc_meta.get("on_protagonist_enters_scene_script"):
                    msgs = await self.manager._execute_inline_script(
                        npc_meta["on_protagonist_enters_scene_script"],
                        "on_protagonist_enters_scene",
                        npc.id,
                    )
                    system_messages.extend(msgs)
                if npc_meta.get("on_protagonist_enters_scene_text"):
                    await self._save_chat_message(
                        "system", npc_meta["on_protagonist_enters_scene_text"]
                    )
                    system_messages.append(npc_meta["on_protagonist_enters_scene_text"])

                attack_mode = npc_meta.get("attack_mode", "PASSIVE")
                if attack_mode == "ATTACK_ON_SIGHT":
                    msg = f"{npc.name} is hostile and attacks on sight!"
                    await self._save_chat_message("system", msg)
                    system_messages.append(msg)

    async def _apply_exit_updates(self, event, system_messages):
        # Process Explicit Map Updates (Exits)
        if not (event.updated_exits):
            return
        try:
            world_map = await AdventureLogic.get_or_create_map(self.db, self.state.template_id)
            for up_exit in event.updated_exits:
                # Update DB row and get exit_type
                exit_res = await self.db.execute(
                    select(WorldExit).where(
                        WorldExit.session_id == self.state.session_id,
                        or_(
                            and_(
                                WorldExit.from_scene_id == up_exit.from_scene_id,
                                WorldExit.to_scene_id == up_exit.to_scene_id,
                            ),
                            and_(
                                WorldExit.from_scene_id == up_exit.to_scene_id,
                                WorldExit.to_scene_id == up_exit.from_scene_id,
                                WorldExit.exit_type == "bidirectional",
                            ),
                        ),
                    )
                )
                exit_db = exit_res.scalars().first()
                exit_type = exit_db.exit_type if exit_db else "one_way"

                MapEngine.register_exit(
                    world_map,
                    up_exit.from_scene_id,
                    up_exit.to_scene_id,
                    is_locked=up_exit.is_locked,
                    exit_type=exit_type,
                )
                if exit_db:
                    was_locked = bool(exit_db.is_locked)
                    exit_db.is_locked = up_exit.is_locked
                    if was_locked and up_exit.is_locked is False:
                        exit_name = (
                            str(exit_db.label or "").strip()
                            or f"{up_exit.from_scene_id} -> {up_exit.to_scene_id}"
                        )
                        msg = f"Exit unlocked: {exit_name}."
                        await self._save_chat_message("system", msg)
                        system_messages.append(msg)
                        if exit_db.on_unlock_success_script:
                            msgs = await self.manager._execute_inline_script(
                                exit_db.on_unlock_success_script,
                                "on_unlock_success",
                                exit_db.id,
                            )
                            system_messages.extend(msgs)
                        if exit_db.on_unlock_success_text:
                            await self._save_chat_message("system", exit_db.on_unlock_success_text)
                            system_messages.append(exit_db.on_unlock_success_text)
        except Exception as e:
            logger.error(f"Manual map exit update failed: {e}")
