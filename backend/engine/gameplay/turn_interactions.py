from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.engine.gameplay.manager import GameTurnManager

from backend.engine.gameplay.turn_containers import ContainerInteractions
from backend.engine.gameplay.turn_debug import DebugInteractions
from backend.engine.gameplay.turn_slash import SlashInteractions
from backend.engine.gameplay.turn_switches import SwitchInteractions
from backend.engine.gameplay.turn_traversal import TraversalInteractions


class TurnInteractionsManager(
    TraversalInteractions,
    DebugInteractions,
    SlashInteractions,
    SwitchInteractions,
    ContainerInteractions,
):
    def __init__(self, manager: GameTurnManager) -> None:
        self.manager = manager
        self.pending_pickup_trigger: dict[str, Any] | None = None
