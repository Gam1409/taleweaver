from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from backend.engine.gameplay.turn_context import TurnContext
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.map_engine import MapEngine
from backend.engine.rule_engine import GameEvent
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene

logger = logging.getLogger(__name__)

CHECKPOINT_REASON_SCENE_CHANGE = "SCENE_CHANGE"


def _sync_lock_overrides(state: Any, edge: WorldExit) -> None:
    overrides = state.exit_states or {}
    keys = {edge.id, f"{edge.from_scene_id}:{edge.to_scene_id}"}
    if edge.exit_type == "bidirectional":
        keys.add(f"{edge.to_scene_id}:{edge.from_scene_id}")
    updates = {}
    for key in keys:
        entry = overrides.get(key)
        if not isinstance(entry, dict) or "is_locked" not in entry:
            continue
        updates[key] = {**entry, "is_locked": edge.is_locked}
    if updates:
        state.exit_states = {**overrides, **updates}


class TurnEventScenes(TurnContext):
    """Apply scenes outcomes in the turn transaction."""

    async def _apply_scene_transition(
        self, event: GameEvent, states: dict[str, Any], system_messages: list[str]
    ) -> bool:
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

    async def _leave_previous_scene(self, system_messages: list[str]) -> str | None:
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
        self,
        event: GameEvent,
        states: dict[str, Any],
        system_messages: list[str],
        old_scene_id: str | None,
        valid_exit: WorldExit | None,
    ) -> None:
        if not old_scene_id or not event.new_scene_id:
            return
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

    async def _fire_arrival_hooks(
        self,
        event: GameEvent,
        states: dict[str, Any],
        system_messages: list[str],
        valid_exit: WorldExit | None,
        new_scene_db: WorldScene | None,
    ) -> None:
        if valid_exit:
            if valid_exit.on_open_exit_script:
                msgs = await self.manager._execute_inline_script(
                    valid_exit.on_open_exit_script, "on_open_exit", valid_exit.id
                )
                system_messages.extend(msgs)
            if valid_exit.on_open_exit_text:
                await self._save_chat_message("system", valid_exit.on_open_exit_text)
                system_messages.append(valid_exit.on_open_exit_text)
            if valid_exit.on_exit_used_script:
                msgs = await self.manager._execute_inline_script(
                    valid_exit.on_exit_used_script, "on_exit_used", valid_exit.id
                )
                system_messages.extend(msgs)
            if valid_exit.on_exit_used_text:
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

    async def _fire_npc_arrival_hooks(
        self, event: GameEvent, states: dict[str, Any], system_messages: list[str]
    ) -> None:
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

    async def _apply_exit_updates(self, event: GameEvent, system_messages: list[str]) -> None:
        if not (event.updated_exits):
            return
        world_map = await self._exit_update_map()
        for up_exit in event.updated_exits:
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
            was_locked = bool(exit_db and exit_db.is_locked)
            if exit_db:
                exit_db.is_locked = up_exit.is_locked
                _sync_lock_overrides(self.state, exit_db)
            self._register_exit_update(world_map, up_exit, exit_db)
            if exit_db is not None and was_locked and up_exit.is_locked is False:
                await self._exit_unlock_effects(exit_db, up_exit, system_messages)

    async def _exit_update_map(self) -> Any:
        """A derived-map error cannot discard an accepted canonical lock update."""
        try:
            return await AdventureLogic.get_or_create_map(self.db, self.state.template_id)
        except SQLAlchemyError:
            raise  # An invalid database transaction must reach the existing turn recovery.
        except Exception:
            logger.warning("Derived map unavailable during exit update", exc_info=True)
            return None

    @staticmethod
    def _register_exit_update(world_map: Any, update: Any, edge: WorldExit | None) -> None:
        if world_map is None:
            return
        try:
            MapEngine.register_exit(
                world_map,
                update.from_scene_id,
                update.to_scene_id,
                is_locked=update.is_locked,
                exit_type=edge.exit_type if edge else "one_way",
            )
        except SQLAlchemyError:
            raise
        except Exception:
            logger.warning("Derived map exit registration failed", exc_info=True)

    async def _exit_unlock_effects(self, edge: WorldExit, update: Any, messages: list[str]) -> None:
        name = str(edge.label or "").strip() or f"{update.from_scene_id} -> {update.to_scene_id}"
        notice = f"Exit unlocked: {name}."
        await self._save_chat_message("system", notice)
        messages.append(notice)
        if edge.on_unlock_success_script:
            messages.extend(
                await self.manager._execute_inline_script(
                    edge.on_unlock_success_script,
                    "on_unlock_success",
                    edge.id,
                )
            )
        if edge.on_unlock_success_text:
            await self._save_chat_message("system", edge.on_unlock_success_text)
            messages.append(edge.on_unlock_success_text)
