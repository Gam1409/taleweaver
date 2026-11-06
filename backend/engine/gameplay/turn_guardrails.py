"""Backward-compatible import path for the guardrails (see ``backend.engine.gameplay.guardrails``)."""

from backend.engine.gameplay.guardrails import TurnGuardrailEnforcer, TurnGuardrailsManager

__all__ = ["TurnGuardrailEnforcer", "TurnGuardrailsManager"]
