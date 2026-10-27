from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from sqlalchemy import and_, func, or_, select

from backend.api.routes.adventures.gameplay_logic import (
    _friendly_llm_error_message,
    _friendly_llm_unexpected_error_message,
)
from backend.engine.trigger_service import TriggerService
from backend.models.world_entity import WorldExit, WorldScene


class TraversalInteractions:
    async def _resolve_traversal_exit(self, exit_ref: str) -> WorldExit | None:
        """Resolves an exit by DB id or 'FROM::TO' scene composite key."""

        if "::" in exit_ref:
            parts = exit_ref.split("::", 1)
            from_id, to_id = parts[0].strip(), parts[1].strip()
            exit_res = await self.db.execute(
                select(WorldExit).where(
                    or_(
                        WorldExit.session_id == self.state.session_id,
                        and_(
                            WorldExit.template_id == self.state.template_id,
                            WorldExit.session_id.is_(None),
                        ),
                    ),
                    or_(
                        and_(
                            func.lower(WorldExit.from_scene_id) == from_id.lower(),
                            func.lower(WorldExit.to_scene_id) == to_id.lower(),
                        ),
                        and_(
                            WorldExit.exit_type == "bidirectional",
                            func.lower(WorldExit.from_scene_id) == to_id.lower(),
                            func.lower(WorldExit.to_scene_id) == from_id.lower(),
                        ),
                    ),
                )
            )
            return exit_res.scalars().first()

        clean_ref = exit_ref.strip()
        exit_res = await self.db.execute(
            select(WorldExit).where(
                or_(
                    WorldExit.session_id == self.state.session_id,
                    and_(
                        WorldExit.template_id == self.state.template_id,
                        WorldExit.session_id.is_(None),
                    ),
                ),
                or_(
                    WorldExit.id == clean_ref,
                    func.lower(WorldExit.id) == clean_ref.lower(),
                ),
            )
        )
        return exit_res.scalars().first()

    async def _fire_traversal_triggers(
        self,
        current_scene_id: str,
        world_exit: WorldExit,
    ) -> list[str]:
        """Fires on_leave_scene, on_open_exit, and on_exit_used triggers."""

        messages: list[str] = []
        old_sc_res = await self.db.execute(
            select(WorldScene).where(
                or_(
                    WorldScene.session_id == self.state.session_id,
                    and_(
                        WorldScene.template_id == self.state.template_id,
                        WorldScene.session_id.is_(None),
                    ),
                ),
                WorldScene.id == current_scene_id,
            )
        )
        old_scene = old_sc_res.scalars().first()
        if old_scene and (old_scene.on_leave_scene_script or old_scene.on_leave_scene_text):
            msgs = await TriggerService.execute_trigger(
                self.db,
                self.state,
                "on_leave_scene",
                old_scene.id,
                script_code=old_scene.on_leave_scene_script,
                narrative_text=old_scene.on_leave_scene_text,
            )
            messages.extend(msgs)

        if world_exit.on_open_exit_script or world_exit.on_open_exit_text:
            msgs = await TriggerService.execute_trigger(
                self.db,
                self.state,
                "on_open_exit",
                world_exit.id,
                script_code=world_exit.on_open_exit_script,
                narrative_text=world_exit.on_open_exit_text,
            )
            messages.extend(msgs)

        if getattr(world_exit, "on_exit_used_script", None) or getattr(
            world_exit, "on_exit_used_text", None
        ):
            msgs = await TriggerService.execute_trigger(
                self.db,
                self.state,
                "on_exit_used",
                world_exit.id,
                script_code=world_exit.on_exit_used_script,
                narrative_text=world_exit.on_exit_used_text,
            )
            messages.extend(msgs)

        return messages

    async def _handle_traverse_exit(
        self, exit_ref: str, language: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Performs scene exit traversal and triggers an LLM narration pass for the new scene."""
        from sqlalchemy import and_, func, or_

        current_scene_id = str(self.state.current_scene_id or "").strip()
        world_exit = await self._resolve_traversal_exit(exit_ref)

        if not world_exit:
            err = f"Exit '{exit_ref}' not found."
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': err})}\n\n"
            return

        if world_exit.is_locked:
            err = str(world_exit.lock_description or "The way is locked.")
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': err})}\n\n"
            return

        target_scene_id = self._traversal_destination(world_exit, current_scene_id)
        if target_scene_id is None:
            err = "This exit does not connect to the current scene."
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': err})}\n\n"
            return

        scene_res = await self.db.execute(
            select(WorldScene).where(
                or_(
                    WorldScene.session_id == self.state.session_id,
                    and_(
                        WorldScene.template_id == self.state.template_id,
                        WorldScene.session_id.is_(None),
                    ),
                ),
                or_(
                    WorldScene.id == target_scene_id,
                    func.lower(WorldScene.id) == str(target_scene_id).lower(),
                ),
            )
        )
        scene = scene_res.scalars().first()
        if not scene:
            err = "The target scene is not available."
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': err})}\n\n"
            return

        for m in await self._fire_traversal_triggers(current_scene_id, world_exit):
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': m})}\n\n"

        self.state.current_scene_id = scene.id
        await self.db.commit()

        if scene.on_enter_scene_script or scene.on_enter_scene_text:
            msgs = await TriggerService.execute_trigger(
                self.db,
                self.state,
                "on_enter_scene",
                scene.id,
                script_code=scene.on_enter_scene_script,
                narrative_text=scene.on_enter_scene_text,
            )
            for m in msgs:
                yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': m})}\n\n"

        # Signal frontend to clear old chat bubbles
        yield f"event: scene_transition\ndata: {json.dumps({'scene_id': scene.id, 'scene_label': scene.label})}\n\n"

        # Build a narration prompt for the new scene
        exit_label = world_exit.label or "the exit"
        scene_label = scene.label or target_scene_id
        narration_prompt = (
            f"[SCENE_TRANSITION] The player moves through {exit_label} and enters {scene_label}. "
            f"Describe the new location vividly: atmosphere, key details, and anything immediately notable. "
            f"Do not summarize previous events."
        )

        yield f"event: status\ndata: {json.dumps({'content': f'Entering {scene_label}...'})}\n\n"

        # Run full LLM cycle to narrate the new scene
        try:
            async for chunk in self._run_llm_cycle(narration_prompt, False, language=language):
                yield chunk
        except Exception as exc:
            user_safe_error = (
                _friendly_llm_error_message(exc) or _friendly_llm_unexpected_error_message()
            )
            yield f"event: error\ndata: {json.dumps({'detail': user_safe_error})}\n\n"

    @staticmethod
    def _traversal_destination(world_exit, current_scene_id):
        if world_exit.from_scene_id.lower() == current_scene_id.lower():
            return world_exit.to_scene_id
        if (
            str(world_exit.exit_type or "").lower() == "bidirectional"
            and world_exit.to_scene_id.lower() == current_scene_id.lower()
        ):
            return world_exit.from_scene_id
        return None
