"""Stable exception types shared by the interpreter and resource checks."""


class ScriptSecurityError(Exception):
    """A script attempted an unsafe operation."""


class ScriptExecutionError(Exception):
    """A script could not be evaluated."""


class ScriptTimeoutError(ScriptExecutionError):
    """A script exceeded its instruction or time budget."""
