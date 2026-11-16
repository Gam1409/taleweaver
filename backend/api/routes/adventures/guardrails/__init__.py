"""Compatibility exports; new code imports backend.engine.gameplay."""

from backend.engine.gameplay.guardrails import TurnGuardrailEnforcer, TurnGuardrailsManager

__all__ = ["TurnGuardrailEnforcer", "TurnGuardrailsManager"]
