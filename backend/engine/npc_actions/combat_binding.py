"""Bind the optional action selector before the existing combat initiative advances."""

import logging
from typing import Any

from backend.core.game_modes import mode_policy
from backend.core.llm_logger import log_structured_event
from backend.engine.chpm import performance
from backend.engine.chpm.control_settings import read
from backend.engine.chpm.schema import Usage
from backend.engine.chpm.state import KEY, load, save
from backend.engine.npc_actions.rpg_port import make_selector
from backend.engine.turn_replay.control import is_debug_toggle

logger = logging.getLogger(__name__)


def bind(manager: Any, command: str) -> None:
    manager.npc_ability_selector = None
    manager.npc_ability_actor_ids = set()
    manager._npc_ability_usage = None
    if not mode_policy(getattr(manager.adventure, "rule_enforcement_mode", None)).combat:
        return
    settings = read((manager.state.entity_states or {}).get(KEY))
    if (
        settings.mode != "live"
        or settings.control_scope != "combat_actions"
        or not settings.action_tools
    ):
        return
    if not getattr(manager, "_replaying", False) and (
        not command.startswith("/")
        or command.lower().startswith("/say ")
        or is_debug_toggle(command)
    ):
        return
    recoverable = getattr(manager, "_turn_replay_recorded", False) and getattr(
        manager, "_recoverable_turn", False
    )
    if not recoverable and not getattr(manager, "_replaying", False):
        logger.warning(
            "NPC combat tools skipped because this input has no recoverable turn boundary."
        )
        return
    usage = Usage(workflow="integrated")
    selector = make_selector(manager, settings, usage=usage)

    async def choose(turn: Any) -> Any:
        if not any(row.get("available") for row in turn.context["abilities"]):
            return None
        token = performance.actor_id.set(turn.frame.actor_id)
        try:
            result = await selector(turn)
            usage.status = "prepared"
            usage.detail = "A combat choice was staged; the initiative owner applies it."
            return result
        except BaseException as exc:
            usage.status = "failed"
            usage.detail = f"Combat selection failed ({type(exc).__name__}); no choice was applied."
            usage.actor_failures[turn.frame.actor_id] = type(exc).__name__
            raise
        finally:
            performance.actor_id.reset(token)
            log_structured_event(
                "npc.combat.selection",
                game_id=manager.game_id,
                operation="chpm",
                phase="rpg_ability",
                actor_id=turn.frame.actor_id,
                usage=usage.model_dump(mode="json"),
            )

    manager.npc_ability_actor_ids = set(sorted(settings.actor_ids)[: settings.max_active_npcs])
    manager.npc_ability_selector = choose
    manager._npc_ability_usage = usage


def complete(manager: Any) -> None:
    """Publish bounded existing Usage after the combat owner completes initiative.

    The normal combat transaction persists it; recovery restores the old ledger
    on cancellation or failure. Failed request metrics remain in owner telemetry.
    """
    usage = getattr(manager, "_npc_ability_usage", None)
    if usage is None or not usage.calls:
        return
    current = load(manager.state)
    if current.settings.control_scope != "combat_actions":
        return
    usage.status = "validated"
    usage.detail = "NPC combat selection completed through the existing initiative owner."
    current.usage = usage.model_copy(deep=True)
    save(manager.state, current, expected_revision=current.revision)
