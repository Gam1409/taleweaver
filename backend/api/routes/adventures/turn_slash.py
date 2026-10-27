from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi.encoders import jsonable_encoder

from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.turn_slash_containers import (
    drop_contents,
    open_container,
    take_all,
)
from backend.api.routes.adventures.turn_slash_inventory import (
    consume_item,
    drop_item,
    equip_item,
    unequip_item,
)
from backend.api.routes.adventures.turn_slash_pickup import take_direct
from backend.api.routes.adventures.turn_slash_walkthrough import reveal_walkthrough

logger = logging.getLogger(__name__)


@dataclass
class SlashCommandState:
    response: str
    halted: bool = False


class SlashInteractions:
    async def _handle_slash(self, user_msg: str, response: str) -> AsyncGenerator[str, None]:
        self.pending_pickup_trigger = None
        if user_msg.lower() == "/map":
            map_payload = await self._build_map_payload()
            final_data = jsonable_encoder(
                {
                    **map_payload,
                    "sheet": await AdventureLogic.build_sheet_snapshot(
                        self.avatar, self.state, self.db
                    ),
                    **self._build_prompt_suggestions_payload(),
                    **self._build_terminal_flags_payload(),
                }
            )
            yield f"event: final\ndata: {json.dumps(final_data)}\n\n"
            return

        command = SlashCommandState(response)
        if command.response.startswith("[TRIGGER_TAKE_DIRECT]"):
            async for chunk in take_direct(self, command):
                yield chunk
            if command.halted:
                return
        elif command.response.startswith("[TRIGGER_WALKTHROUGH_REVEAL]"):
            await reveal_walkthrough(self, command)

        async for chunk in self._run_slash_item_commands(command):
            yield chunk
        async for chunk in self._finish_slash_command(command):
            yield chunk

    async def _run_slash_item_commands(self, command):
        if command.response.startswith("[TRIGGER_DROP]"):
            async for chunk in drop_item(self, command):
                yield chunk
        await self._run_slash_container_commands(command)
        if command.response.startswith("[TRIGGER_EQUIP]"):
            async for chunk in equip_item(self, command):
                yield chunk
        if command.response.startswith("[TRIGGER_UNEQUIP]"):
            async for chunk in unequip_item(self, command):
                yield chunk
        if command.response.startswith("[TRIGGER_CONSUME]"):
            async for chunk in consume_item(self, command):
                yield chunk

    async def _run_slash_container_commands(self, command):
        if command.response.startswith("[TRIGGER_OPEN]"):
            await open_container(self, command)
        if command.response.startswith("[TRIGGER_SWITCH]"):
            switch_args = command.response.replace("[TRIGGER_SWITCH]", "").strip()
            command.response = await self._execute_switch_command(switch_args)
        if command.response.startswith("[TRIGGER_CONTAINER_TAKE_ALL]"):
            await take_all(self, command)
        if command.response.startswith("[TRIGGER_CONTAINER_TAKE_ITEM]"):
            take_args = command.response.replace("[TRIGGER_CONTAINER_TAKE_ITEM]", "").strip()
            command.response = await self._take_single_container_item(take_args)
        if command.response.startswith("[TRIGGER_CONTAINER_DROP_SCENE]"):
            await drop_contents(self, command)

    async def _finish_slash_command(self, command):
        if command.response and not command.response.startswith("[TRIGGER_"):
            await self._save_chat_message("system", command.response)
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': command.response})}\n\n"

        # Check sequence progress deterministically
        adv = getattr(self.manager, "adventure", None)
        script_context = None
        if hasattr(self, "manager") and hasattr(self.manager, "_build_script_context"):
            try:
                script_context = await self.manager._build_script_context()
            except Exception as exc:
                logger.warning("Could not build script context for sequence evaluation: %s", exc)
        seq_messages = AdventureLogic.evaluate_sequence_progress(
            adventure=adv,
            state=self.state,
            avatar=self.avatar,
            script_context=script_context,
        )
        if seq_messages:
            for seq_msg in seq_messages:
                await self._save_chat_message("system", seq_msg)
                yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': seq_msg})}\n\n"

        await self.db.commit()
        if self.pending_pickup_trigger:
            # Caller chains an LLM pass, which emits the final event itself.
            return
        final_data = jsonable_encoder(
            {
                "sheet": await AdventureLogic.build_sheet_snapshot(
                    self.avatar, self.state, self.db
                ),
                "entities": await AdventureLogic.build_session_entities(self.db, self.state),
                "combat": AdventureLogic.get_combat_snapshot(self.state),
                "active_sequence": AdventureLogic.resolve_active_sequence(adv, self.state),
                **self._build_prompt_suggestions_payload(),
                **self._build_terminal_flags_payload(),
            }
        )
        yield f"event: final\ndata: {json.dumps(final_data)}\n\n"
        self.stop_requested = True  # Stop after direct slash response
