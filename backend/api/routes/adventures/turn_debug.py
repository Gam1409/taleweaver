from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.debug_engine import DebugEngine
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity


class DebugInteractions:
    async def _handle_debug(self, user_msg: str) -> AsyncGenerator[str, None]:
        cmd_args = user_msg[7:].strip()
        debug_info = await DebugEngine.handle_debug_command(
            self.db,
            self.state,
            cmd_args,
            user=self.user,
            adventure=self.adventure,
            avatar=self.avatar,
        )

        # Handle status overrides from debug engine
        if debug_info.startswith("[TRIGGER_GAME_OVER]"):
            await self._finalize_session("game_over", debug_info)
            debug_info = "DEBUG: Session forced to GAME OVER."
        elif debug_info.startswith("[TRIGGER_GAME_COMPLETED]"):
            await self._finalize_session("completed", debug_info)
            debug_info = "DEBUG: Session forced to COMPLETED."
        elif debug_info.startswith("[TRIGGER_WALKTHROUGH_REVEAL_FREE]"):
            self.state.is_walkthrough_revealed = True
            debug_info = debug_info[33:].strip()
        elif debug_info.startswith("[TRIGGER_GEN_ITEM]"):
            prompt = debug_info.replace("[TRIGGER_GEN_ITEM]", "").strip()
            async for chunk in self._handle_debug_gen_item(prompt):
                yield chunk
            return
        elif debug_info.startswith("[TRIGGER_NPC_DROP_ITEMS]"):
            dropped_info = await self._debug_drop_npc_items()
            debug_info = f"DEBUG: {dropped_info}"

        # New: Combat Debug Commands
        elif cmd_args == "win_fight":
            debug_info = await self._debug_win_fight(debug_info)
        elif cmd_args == "loose_fight":
            debug_info = self._debug_lose_fight(debug_info)

        if debug_info.startswith("[DEBUG_LOG_OFF]"):
            await self.db.commit()
            map_payload = await self._build_map_payload()
            final_data = jsonable_encoder(
                {
                    **map_payload,
                    "sheet": await AdventureLogic.build_sheet_snapshot(
                        self.avatar, self.state, self.db
                    ),
                    "combat": AdventureLogic.get_combat_snapshot(self.state),
                    "awards": self.adventure.awards if self.adventure else [],
                    "game_over_reason": self.state.session.status_note
                    if self.state.session
                    else None,
                    **self._build_prompt_suggestions_payload(),
                    **self._build_terminal_flags_payload(),
                    "status": "success",
                }
            )
            yield f"event: final\ndata: {json.dumps(final_data)}\n\n"
            return

        # Save the user's /debug command to DB so it can be deleted in debug mode.
        user_chat_msg = ChatMessage(session_id=self.state.session_id, role="user", content=user_msg)
        self.db.add(user_chat_msg)
        await self.db.flush()
        user_msg_id = str(user_chat_msg.id)

        # Send debug info as a system message so it appears in chat.
        # Include both IDs so the frontend can attach them for deletion.
        system_chat_msg = ChatMessage(
            session_id=self.state.session_id, role="system", content=debug_info
        )
        self.db.add(system_chat_msg)
        await self.db.flush()
        system_msg_id = str(system_chat_msg.id)

        await self.db.commit()
        yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': debug_info, 'is_debug': True, 'id': system_msg_id, 'user_msg_id': user_msg_id})}\n\n"

        final_data = jsonable_encoder(
            {
                "sheet": await AdventureLogic.build_sheet_snapshot(
                    self.avatar, self.state, self.db
                ),
                "entities": await AdventureLogic.build_session_entities(self.db, self.state),
                "combat": AdventureLogic.get_combat_snapshot(self.state),
                **self._build_prompt_suggestions_payload(),
                **self._build_terminal_flags_payload(),
                "status": "success",
            }
        )
        yield f"event: final\ndata: {json.dumps(final_data)}\n\n"

    async def _handle_debug_gen_item(self, prompt: str) -> AsyncGenerator[str, None]:
        """Debug helper to force-generate an item based on a prompt."""
        instruction = (
            f"DEBUG COMMAND: The user wants you to generate an item now. Instruction: {prompt}"
        )
        # We temporarily set the prompt as if it was the user message
        async for chunk in self._run_llm_cycle(instruction, self.avatar):
            yield chunk

        map_payload = await self._build_map_payload()
        final_data = jsonable_encoder(
            {
                **map_payload,
                "sheet": await AdventureLogic.build_sheet_snapshot(
                    self.avatar, self.state, self.db
                ),
                "combat": AdventureLogic.get_combat_snapshot(self.state),
                "awards": self.adventure.awards,
                "game_over_reason": self.state.session.status_note if self.state.session else None,
                **self._build_prompt_suggestions_payload(),
                **self._build_terminal_flags_payload(),
                "status": "success",
            }
        )
        yield f"event: final\ndata: {json.dumps(final_data)}\n\n"

    async def _debug_drop_npc_items(self) -> str:
        # Find all NPCs in the current scene
        res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id,
                WorldEntity.entity_type == "NPC",
                WorldEntity.current_scene_id == self.state.current_scene_id,
            )
        )
        npcs = res.scalars().all()
        if not npcs:
            return "No NPCs found in the current scene."

        overrides = self.state.entity_states or {}
        dropped_items_summary = []

        for npc in npcs:
            # Determine NPC's current inventory
            npc_inv = overrides.get(npc.id, {}).get("inventory")
            if npc_inv is None:
                npc_inv = npc.inventory or []

            if not npc_inv:
                continue

            # Drop each item in scene
            for item in npc_inv:
                await self._spawn_scene_item(item)
                dropped_items_summary.append(f"{item.get('name') or 'Item'} (from {npc.name})")

            # Clear NPC's inventory in DB
            npc.inventory = []
            self.db.add(npc)

            # Clear NPC's inventory in session state overrides
            states = dict(self.state.entity_states or {})
            if npc.id not in states:
                states[npc.id] = {}
            states[npc.id]["inventory"] = []
            self.state.entity_states = states
            flag_modified(self.state, "entity_states")

        if not dropped_items_summary:
            return "No items to drop from NPCs in the current scene."

        return f"Dropped NPC items: {', '.join(dropped_items_summary)}"

    async def _debug_win_fight(self, debug_info):
        combat = self._read_combat_state()
        if combat and combat.get("active"):
            combat["active"] = False
            combat["outcome"] = "victory"
            combat["enemy"]["hp"] = 0

            # Mirror normal victory behavior so debug wins can be used for loot testing.
            enemy_id = combat["enemy"]["id"]
            enemy_res = await self.db.execute(
                select(WorldEntity).where(
                    WorldEntity.id == enemy_id,
                    WorldEntity.session_id == self.game_id,
                )
            )
            enemy_ent = enemy_res.scalars().first()

            xp_gained = 0
            if enemy_ent:
                xp_gained = self._award_combat_victory_xp(enemy_ent)
            combat["status_note"] = f"Combat won via debug command. (+{xp_gained} XP)"

            loot_items = await self._normalize_loot_items(
                list(
                    combat.get("enemy", {}).get("inventory")
                    or (enemy_ent.inventory if enemy_ent else [])
                    or []
                )
            )
            combat["loot_pending"] = bool(loot_items)
            combat["loot_items"] = loot_items

            states = dict(self.state.entity_states or {})
            if enemy_id not in states:
                states[enemy_id] = {}
            states[enemy_id]["hp"] = 0
            states[enemy_id]["inventory"] = []
            enemy_is_killable = (
                states[enemy_id].get("is_killable")
                if "is_killable" in states[enemy_id]
                else enemy_ent.is_killable
                if enemy_ent
                else True
            )
            if enemy_is_killable:
                states[enemy_id]["is_defeated"] = True
                states[enemy_id]["is_attackable"] = False
            self.state.entity_states = states
            flag_modified(self.state, "entity_states")

            self._append_combat_log(combat, combat["status_note"], "outcome")
            if loot_items:
                loot_msg = (
                    "Victory! Loot available. Use /loot take <item>, /loot leave <item>, /loot done"
                )
                self._append_combat_log(combat, loot_msg, "loot")
            self._set_combat_state(combat)
            debug_info = f"DEBUG: Combat forced to VICTORY (loot phase enabled). (+{xp_gained} XP)"

        return debug_info

    def _debug_lose_fight(self, debug_info):
        combat = self._read_combat_state()
        if combat and combat.get("active"):
            combat["active"] = False
            combat["outcome"] = "defeat"
            combat["player"]["hp"] = 0
            combat["status_note"] = "Combat lost via debug command."

            # Sync back to avatar
            self.avatar.hp = 0

            self._append_combat_log(combat, combat["status_note"], "outcome")
            self._set_combat_state(combat)
            debug_info = "DEBUG: Combat forced to DEFEAT."

        return debug_info
