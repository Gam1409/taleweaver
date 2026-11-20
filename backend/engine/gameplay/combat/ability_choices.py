"""Host-bound choices for the existing NPC combat turn, never a second turn."""

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

from backend.core.game_modes import mode_policy
from backend.engine.combat.initiative import PLAYER_ID
from backend.engine.combat.special_attacks import normalize_special_actions
from backend.engine.gameplay.combat.context import is_enemy_alive
from backend.engine.gameplay.combat.resources import npc_can_afford
from backend.engine.npc_presence import physically_present

MAX_ABILITIES = 32


@dataclass(frozen=True)
class Frame:
    session_id: str
    scene_id: str
    encounter_id: str
    actor_id: str
    round: int
    turn_index: int
    signature: str


@dataclass(frozen=True)
class AbilityTurn:
    frame: Frame
    context: dict


@dataclass(frozen=True)
class Choice:
    frame: Frame
    ability_id: str
    target_id: str | None = None


def _actor(owner: Any, combat: dict, actor_id: str) -> dict:
    mode = getattr(owner.adventure, "rule_enforcement_mode", None)
    if not mode_policy(mode).combat or not combat.get("active"):
        raise ValueError("Ability selection requires active RPG combat.")
    order = combat.get("initiative") or []
    index = int(combat.get("turn_index") or 0)
    current = order[index].get("id") if 0 <= index < len(order) else None
    if current != actor_id or actor_id == PLAYER_ID:
        raise ValueError("This NPC does not own the current combat turn.")
    enemies: list[dict[str, Any]] = combat.get("enemies", [])
    matches = [row for row in enemies if row.get("id") == actor_id]
    if len(matches) != 1 or not matches[0].get("engaged") or not is_enemy_alive(matches[0]):
        raise ValueError("The NPC is not an active combat participant.")
    return matches[0]


async def _definition(owner: Any, actor_id: str) -> tuple[Any, list[dict]]:
    npc = await owner._load_session_entity(actor_id)
    if npc is None or str(npc.entity_type).upper() != "NPC":
        raise ValueError("The NPC is unavailable in this session.")
    states = owner.state.entity_states or {}
    override = states.get(actor_id) or {}
    if (
        override.get("current_scene_id", npc.current_scene_id) != owner.state.current_scene_id
        or override.get("is_hidden", npc.is_hidden)
        or override.get("is_defeated", False)
        or owner._entity_stat(npc, "hp", 1) <= 0
        or not physically_present(npc, owner.state)
    ):
        raise ValueError("The NPC is no longer present in the combat scene.")
    raw = (npc.metadata_json or {}).get("special_actions") or []
    actions = normalize_special_actions(raw)
    ids = [action["id"] for action in actions]
    if len(ids) != len(set(ids)):
        raise ValueError("Ambiguous ability identifiers require correction.")
    return npc, actions


def _signature(owner: Any, combat: dict, enemy: dict, npc: Any, actions: list[dict]) -> str:
    current = {
        "session": owner.game_id,
        "scene": owner.state.current_scene_id,
        "encounter": combat["encounter_id"],
        "round": combat.get("round"),
        "turn_index": combat.get("turn_index"),
        "initiative": combat.get("initiative"),
        "enemy": enemy,
        "resources": {key: owner._entity_stat(npc, key, 0) for key in ("hp", "mana", "stamina")},
        "definition": (npc.metadata_json or {}).get("special_actions"),
        "actions": actions,
        "player": {key: getattr(owner.avatar, key, None) for key in ("hp", "mana", "stamina")},
        "damage_allowed": bool(getattr(owner.adventure, "npcs_can_damage_protagonist", True)),
        "controller": id(getattr(owner.manager, "npc_ability_selector", None)),
        "controller_actors": sorted(getattr(owner.manager, "npc_ability_actor_ids", None) or ()),
    }
    return sha256(
        json.dumps(current, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def prepare(owner: Any, combat: dict, actor_id: str) -> AbilityTurn:
    """Capture before inference; assigning an encounter identity is host bookkeeping."""
    enemy = _actor(owner, combat, actor_id)
    npc, actions = await _definition(owner, actor_id)
    if "encounter_id" not in combat:
        combat["encounter_id"] = uuid4().hex
    if not isinstance(combat["encounter_id"], str) or not combat["encounter_id"]:
        raise ValueError("The encounter identity is unavailable.")
    frame = Frame(
        owner.game_id,
        owner.state.current_scene_id,
        combat["encounter_id"],
        actor_id,
        int(combat.get("round") or 1),
        int(combat.get("turn_index") or 0),
        _signature(owner, combat, enemy, npc, actions),
    )
    damage_allowed = bool(getattr(owner.adventure, "npcs_can_damage_protagonist", True))
    abilities = [_public(action, enemy, damage_allowed) for action in actions[:MAX_ABILITIES]]
    return AbilityTurn(
        frame,
        {
            "actor_id": actor_id,
            "scene_id": frame.scene_id,
            "round": frame.round,
            "resources": {
                key: int(enemy.get(key) or 0)
                for key in ("hp", "max_hp", "mana", "max_mana", "stamina", "max_stamina")
            },
            "abilities": abilities,
            "omitted_abilities": max(0, len(actions) - MAX_ABILITIES),
            "target_ids": [PLAYER_ID] if damage_allowed else [],
            "meaning": "Choose for this NPC's existing combat turn; nothing has executed.",
        },
    )


def _public(action: dict, enemy: dict, damage_allowed: bool) -> dict:
    return {
        "id": action["id"],
        "name": str(action["name"])[:160],
        "description": str(action.get("description") or "")[:400],
        "category": action["category"],
        "cost": {
            "type": action["cost_type"],
            "amount": action["cost"],
            "free_without_pool": int(enemy.get(f"max_{action['cost_type']}") or 0) <= 0,
        },
        "targets_enemy": action["targets_enemy"],
        "target_ids": [PLAYER_ID] if action["targets_enemy"] else [enemy["id"]],
        "effects": deepcopy(action["effects"]),
        "success_stat": action["success_stat"],
        "difficulty": action["difficulty"],
        "available": npc_can_afford(action, enemy)
        and (damage_allowed or not action["targets_enemy"]),
    }


async def resolve(owner: Any, combat: dict, choice: Choice) -> dict:
    """Recheck the live owner after inference and return only its authored definition."""
    if not isinstance(choice, Choice) or not isinstance(choice.frame, Frame):
        raise ValueError("Use a host-bound ability choice.")
    if not isinstance(choice.ability_id, str) or (
        choice.target_id is not None and not isinstance(choice.target_id, str)
    ):
        raise ValueError("Use exact string ability and target identifiers.")
    current = await prepare(owner, combat, choice.frame.actor_id)
    if current.frame != choice.frame:
        raise ValueError("The combat turn changed while choosing an ability.")
    _, actions = await _definition(owner, choice.frame.actor_id)
    action = next((row for row in actions if row["id"] == choice.ability_id), None)
    if action is None:
        raise ValueError("Choose an exact authored ability ID.")
    enemy = _actor(owner, combat, choice.frame.actor_id)
    if not npc_can_afford(action, enemy):
        raise ValueError("The NPC lacks the resource required for this ability.")
    if action["targets_enemy"] and not bool(
        getattr(owner.adventure, "npcs_can_damage_protagonist", True)
    ):
        raise ValueError("This adventure disables that target effect.")
    target = PLAYER_ID if choice.target_id == "@player" else choice.target_id
    valid = {None, PLAYER_ID} if action["targets_enemy"] else {None, choice.frame.actor_id}
    if target not in valid:
        raise ValueError("This ability cannot use that target.")
    return deepcopy(action)
