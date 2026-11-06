"""Facade combining every Pass 1.5 guardrail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.engine.gameplay.guardrails.base import GuardrailBase
from backend.engine.gameplay.guardrails.containers import ContainerGuardMixin
from backend.engine.gameplay.guardrails.crafting import CraftingGuardMixin
from backend.engine.gameplay.guardrails.exits import ExitGuardMixin
from backend.engine.gameplay.guardrails.inspect import InspectGuardMixin
from backend.engine.gameplay.guardrails.progress import ProgressGuardMixin
from backend.engine.gameplay.guardrails.reading import ReadingMixin
from backend.engine.gameplay.guardrails.reveals import RevealGuardMixin

if TYPE_CHECKING:
    from backend.engine.gameplay.manager import GameTurnManager


class TurnGuardrailsManager(
    InspectGuardMixin,
    ContainerGuardMixin,
    ExitGuardMixin,
    CraftingGuardMixin,
    RevealGuardMixin,
    ProgressGuardMixin,
    ReadingMixin,
    GuardrailBase,
):
    """Server-side visibility authority and Pass 1.5 rule validations & reversions."""

    def __init__(self, manager: GameTurnManager) -> None:
        self.manager = manager


TurnGuardrailEnforcer = TurnGuardrailsManager
