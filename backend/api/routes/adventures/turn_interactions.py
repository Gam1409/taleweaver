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
    SlashInteractions,
    SwitchInteractions,
    ContainerInteractions,
):
    def __init__(self, manager: GameTurnManager) -> None:
        self.manager = manager
        self.pending_pickup_trigger: dict[str, Any] | None = None
