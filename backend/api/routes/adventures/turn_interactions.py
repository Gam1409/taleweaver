from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.api.routes.adventures.gameplay_logic import GameTurnManager

from backend.api.routes.adventures.turn_containers import ContainerInteractions
from backend.api.routes.adventures.turn_debug import DebugInteractions
from backend.api.routes.adventures.turn_slash import SlashInteractions
from backend.api.routes.adventures.turn_switches import SwitchInteractions
from backend.api.routes.adventures.turn_traversal import TraversalInteractions


class TurnInteractionsManager(
    TraversalInteractions,
    DebugInteractions,
    SwitchInteractions,
    SlashInteractions,
    ContainerInteractions,
):
    def __init__(self, manager: GameTurnManager) -> None:
        self.manager = manager
        self.pending_pickup_trigger: dict[str, Any] | None = None

    @property
    def db(self):
        return self.manager.db

    @property
    def game_id(self):
        return self.manager.game_id

    @property
    def user(self):
        return self.manager.user

    @property
    def state(self):
        return self.manager.state

    @property
    def avatar(self):
        return self.manager.avatar

    @property
    def adventure(self):
        return self.manager.adventure

    @property
    def stop_requested(self):
        return self.manager.stop_requested

    @stop_requested.setter
    def stop_requested(self, val):
        self.manager.stop_requested = val

    def _queue_checkpoint(self, *args, **kwargs):
        return self.manager._queue_checkpoint(*args, **kwargs)

    async def _persist_pending_checkpoints(self, *args, **kwargs):
        return await self.manager._persist_pending_checkpoints(*args, **kwargs)

    def _append_combat_log(self, *args, **kwargs):
        return self.manager._append_combat_log(*args, **kwargs)

    def _award_combat_victory_xp(self, *args, **kwargs):
        return self.manager._award_combat_victory_xp(*args, **kwargs)

    def _build_map_payload(self, *args, **kwargs):
        return self.manager._build_map_payload(*args, **kwargs)

    def _build_prompt_suggestions_payload(self, *args, **kwargs):
        return self.manager._build_prompt_suggestions_payload(*args, **kwargs)

    def _build_terminal_flags_payload(self, *args, **kwargs):
        return self.manager._build_terminal_flags_payload(*args, **kwargs)

    async def _check_special_action_unlocks(self, *args, **kwargs):
        return await self.manager._check_special_action_unlocks(*args, **kwargs)

    def _consume_item_now(self, *args, **kwargs):
        return self.manager._consume_item_now(*args, **kwargs)

    def _emit_combat_final(self, *args, **kwargs):
        return self.manager._emit_combat_final(*args, **kwargs)

    async def _finalize_session(self, *args, **kwargs):
        return await self.manager._finalize_session(*args, **kwargs)

    async def _find_scene_npc_by_hint(self, *args, **kwargs):
        return await self.manager._find_scene_npc_by_hint(*args, **kwargs)

    def _is_container_item(self, *args, **kwargs):
        return self.manager._is_container_item(*args, **kwargs)

    def _is_container_locked(self, *args, **kwargs):
        return self.manager._is_container_locked(*args, **kwargs)

    def _is_npc_defeated(self, *args, **kwargs):
        return self.manager._is_npc_defeated(*args, **kwargs)

    def _normalize_loot_items(self, *args, **kwargs):
        return self.manager._normalize_loot_items(*args, **kwargs)

    def _read_combat_state(self, *args, **kwargs):
        return self.manager._read_combat_state(*args, **kwargs)

    def _run_llm_cycle(self, *args, **kwargs):
        return self.manager._run_llm_cycle(*args, **kwargs)

    async def _save_chat_message(self, *args, **kwargs):
        return await self.manager._save_chat_message(*args, **kwargs)

    def _set_combat_state(self, *args, **kwargs):
        return self.manager._set_combat_state(*args, **kwargs)

    async def _spawn_scene_item(self, *args, **kwargs):
        return await self.manager._spawn_scene_item(*args, **kwargs)
