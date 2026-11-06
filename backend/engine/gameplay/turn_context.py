"""Typed access to the initialized turn manager shared by interaction and event handlers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.snapshot import AdventureSnapshot
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity

if TYPE_CHECKING:
    from backend.engine.gameplay.manager import GameTurnManager


class TurnContext:
    manager: GameTurnManager
    pending_pickup_trigger: dict[str, Any] | None

    @property
    def db(self) -> AsyncSession:
        return self.manager.db

    @property
    def game_id(self) -> str:
        return self.manager.game_id

    @property
    def user(self) -> User:
        return self.manager.user

    @property
    def state(self) -> SessionState:
        value = self.manager.state
        if value is None:
            raise RuntimeError("Initialize the turn manager before accessing state.")
        return value

    @property
    def avatar(self) -> Avatar:
        value = self.manager.avatar
        if value is None:
            raise RuntimeError("Initialize the turn manager before accessing avatar.")
        return value

    @property
    def adventure(self) -> AdventureTemplate | AdventureSnapshot | None:
        return self.manager.adventure

    @property
    def stop_requested(self) -> bool:
        return self.manager.stop_requested

    @stop_requested.setter
    def stop_requested(self, value: bool) -> None:
        self.manager.stop_requested = value

    def _append_combat_log(
        self,
        combat: dict[str, Any],
        text: str,
        entry_type: str = "log",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.manager._append_combat_log(combat, text, entry_type, data)

    async def _apply_adventure_generator_tools(
        self, event: Any, stream_callback: Callable[[str], Awaitable[None] | None] | None = None
    ) -> None:
        await self.manager._apply_adventure_generator_tools(event, stream_callback)

    def _apply_gm_notes_update(
        self, remember_notes: list[str] | None, forget_notes: list[str] | None, clear_notes: bool
    ) -> None:
        self.manager._apply_gm_notes_update(remember_notes, forget_notes, clear_notes)

    def _award_combat_victory_xp(self, enemy_ent: WorldEntity) -> int:
        return self.manager._award_combat_victory_xp(enemy_ent)

    async def _build_map_payload(self) -> dict[str, Any]:
        return await self.manager._build_map_payload()

    def _build_prompt_suggestions_payload(self) -> dict[str, Any]:
        return self.manager._build_prompt_suggestions_payload()

    def _build_terminal_flags_payload(self) -> dict[str, Any]:
        return self.manager._build_terminal_flags_payload()

    async def _check_special_action_unlocks(self, condition_type: str, target_id: str) -> None:
        await self.manager._check_special_action_unlocks(condition_type, target_id)

    async def _collect_existing_item_ids(self) -> set[str]:
        return await self.manager._collect_existing_item_ids()

    def _consume_item_now(self, item_name: str) -> str:
        return self.manager._consume_item_now(item_name)

    def _emit_combat_final(self, status_note: str | None = None) -> AsyncGenerator[str, None]:
        return self.manager._emit_combat_final(status_note)

    async def _finalize_session(self, status: str, note: str | None = None) -> None:
        await self.manager._finalize_session(status, note)

    async def _find_scene_npc_by_hint(self, target_hint: str) -> WorldEntity | None:
        return await self.manager._find_scene_npc_by_hint(target_hint)

    def _is_container_item(self, item: Any) -> bool:
        return self.manager._is_container_item(item)

    def _is_container_locked(
        self, scene_container: WorldEntity | None, inventory_container: dict[str, Any] | None
    ) -> bool:
        return self.manager._is_container_locked(scene_container, inventory_container)

    def _is_npc_defeated(self, npc: WorldEntity) -> bool:
        return self.manager._is_npc_defeated(npc)

    async def _normalize_loot_items(self, items: list[Any]) -> list[dict[str, Any]]:
        return await self.manager._normalize_loot_items(items)

    async def _persist_pending_checkpoints(self) -> list[dict[str, Any]]:
        return await self.manager._persist_pending_checkpoints()

    def _queue_checkpoint(self, reason: str, *, scene_label: str | None = None) -> None:
        self.manager._queue_checkpoint(reason, scene_label=scene_label)

    def _read_combat_state(self) -> dict[str, Any]:
        return self.manager._read_combat_state()

    def _run_llm_cycle(
        self,
        user_msg: str,
        auto_visualize: bool,
        language: str | None = None,
        narration_only: bool = False,
    ) -> AsyncGenerator[str, None]:
        return self.manager._run_llm_cycle(user_msg, auto_visualize, language, narration_only)

    async def _save_chat_message(self, role: str, content: str) -> ChatMessage:
        return await self.manager._save_chat_message(role, content)

    def _set_combat_state(self, combat: dict[str, Any]) -> None:
        self.manager._set_combat_state(combat)

    async def _spawn_scene_item(self, item: dict[str, Any]) -> None:
        await self.manager._spawn_scene_item(item)
