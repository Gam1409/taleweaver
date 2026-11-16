"""Initiative order, round progression and encounter outcomes."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from backend.engine.combat.initiative import PLAYER_ID, describe_initiative, roll_initiative
from backend.engine.gameplay.combat.context import (
    engaged_enemies,
    find_enemy,
)
from backend.engine.gameplay.combat.enemy_ai import CombatEnemyMixin
from backend.engine.gameplay.combat.outcomes import LOOT_HINT

__all__ = ["CombatRoundMixin", "LOOT_HINT"]

MAX_TURN_STEPS = 64


class CombatRoundMixin(CombatEnemyMixin):
    """Keeps the initiative order moving and detects victory or defeat."""

    def _initiative_participants(self, combat: dict[str, Any]) -> list[dict[str, Any]]:
        player = combat.get("player") or {}
        player_dex = int((player.get("stats") or {}).get("dexterity", self.avatar.dexterity or 0))
        player_dex += int((player.get("modifiers") or {}).get("dexterity", 0))
        participants = [{"id": PLAYER_ID, "name": self.avatar.name, "dexterity": player_dex}]
        for enemy in engaged_enemies(combat):
            dex = int(enemy.get("dexterity_mod") or 0) + int(
                (enemy.get("modifiers") or {}).get("dexterity", 0)
            )
            participants.append({"id": enemy["id"], "name": enemy["name"], "dexterity": dex})
        return participants

    def _roll_round_initiative(self, combat: dict[str, Any]) -> None:
        order = roll_initiative(self._initiative_participants(combat))
        combat["initiative"] = order
        combat["turn_index"] = 0
        round_no = int(combat.get("round") or 1)
        self._append_combat_log(
            combat,
            describe_initiative(order, round_no),
            "initiative",
            {"kind": "initiative", "round": round_no, "order": order},
        )

    @staticmethod
    def _current_actor_id(combat: dict[str, Any]) -> str | None:
        order = combat.get("initiative") or []
        idx = int(combat.get("turn_index") or 0)
        return order[idx]["id"] if 0 <= idx < len(order) else None

    def _set_turn_marker(self, combat: dict[str, Any]) -> None:
        actor = self._current_actor_id(combat)
        combat["active_actor"] = actor
        combat["turn"] = "player" if actor == PLAYER_ID else "enemy"

    def _enemy_can_act(self, combat: dict[str, Any], actor_id: str | None) -> bool:
        enemy = find_enemy(combat, actor_id)
        return bool(enemy and enemy in engaged_enemies(combat))

    async def _advance_until_player(
        self, combat: dict[str, Any], skip_current: bool
    ) -> AsyncGenerator[str, None]:
        """Walks the initiative order, resolving NPC turns until the player acts or combat ends."""
        if skip_current:
            combat["turn_index"] = int(combat.get("turn_index") or 0) + 1

        for _ in range(MAX_TURN_STEPS):
            if not combat.get("active"):
                break
            if int(combat.get("turn_index") or 0) >= len(combat.get("initiative") or []):
                combat["round"] = int(combat.get("round") or 1) + 1
                self._roll_round_initiative(combat)
                continue
            actor = self._current_actor_id(combat)
            if actor == PLAYER_ID:
                self._announce_player_turn(combat)
                break
            if self._enemy_can_act(combat, actor):
                self._set_turn_marker(combat)
                async for chunk in self._resolve_enemy_turn(actor, combat):
                    yield chunk
            combat["turn_index"] = int(combat.get("turn_index") or 0) + 1

        if combat.get("active"):
            self._set_turn_marker(combat)
        self._set_combat_state(combat)

    def _announce_player_turn(self, combat: dict[str, Any]) -> None:
        self._set_turn_marker(combat)
        text = f"Round {combat.get('round', 1)}: {self.avatar.name}'s turn."
        self._append_combat_log(combat, text, "turn", {"kind": "turn", "actor": PLAYER_ID})
