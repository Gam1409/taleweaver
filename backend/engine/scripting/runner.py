"""
Script runner for dispatching and executing adventure event triggers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.engine.scripting.context import GameContext, ScriptChangeset
from backend.engine.scripting.sandbox import (
    SafeAstInterpreter,
    ScriptExecutionError,
    ScriptSecurityError,
    ScriptTimeoutError,
)

logger = logging.getLogger(__name__)


class ScriptRunner:
    """Dispatches and evaluates scripts attached to an adventure."""

    def __init__(self, scripts: list[dict[str, Any]] | None = None):
        self.scripts = scripts or []
        self.interpreter = SafeAstInterpreter()

    @staticmethod
    def _should_run_script(script: Any, trigger: str, target_id: Optional[str]) -> bool:
        if not isinstance(script, dict):
            return False
        if script.get("is_active") is False:
            return False
        if script.get("trigger") != trigger:
            return False
        s_target = script.get("target_id") or script.get("target")
        if s_target and (not target_id or s_target != target_id):
            return False
        return bool(script.get("code", "").strip())

    def _run_single_script(
        self,
        script: dict[str, Any],
        trigger: str,
        target_id: Optional[str],
        context: GameContext,
    ) -> None:
        code = script.get("code", "").strip()
        script_id = script.get("id", "UNKNOWN_SCRIPT")
        logger.info(
            f"[ScriptRunner] Executing script '{script_id}' on trigger '{trigger}' (target={target_id})"
        )
        scope = {"tw": context, "game": context}
        try:
            self.interpreter.execute(code, scope)
        except ScriptSecurityError as sse:
            logger.error(f"[ScriptRunner] Security violation in script '{script_id}': {sse}")
        except ScriptTimeoutError as ste:
            logger.error(
                f"[ScriptRunner] Timeout/instruction limit exceeded in script '{script_id}': {ste}"
            )
        except ScriptExecutionError as see:
            logger.error(f"[ScriptRunner] Runtime error in script '{script_id}': {see}")
        except Exception as exc:
            logger.exception(
                f"[ScriptRunner] Unexpected error executing script '{script_id}': {exc}"
            )

    def run_trigger(
        self,
        trigger: str,
        context: GameContext,
        target_id: Optional[str] = None,
    ) -> ScriptChangeset:
        """
        Finds and executes all scripts matching the specified trigger and optional target_id.
        Mutations are accumulated directly in context.changeset.
        """
        for script in self.scripts:
            if not self._should_run_script(script, trigger, target_id):
                continue
            self._run_single_script(script, trigger, target_id, context)

        return context.changeset

    def execute_code(self, code: str, scope: dict[str, Any], script_id: str = "INLINE") -> None:
        """Executes a single inline code block directly."""
        try:
            self.interpreter.execute(code, scope)
        except Exception as exc:
            logger.exception(
                f"[ScriptRunner] Unexpected error executing inline script '{script_id}': {exc}"
            )
            tw = scope.get("tw") or scope.get("game")
            if tw and hasattr(tw, "changeset") and hasattr(tw.changeset, "narrative_messages"):
                tw.changeset.narrative_messages.append(f"[Script Error ({script_id})]: {exc}")
