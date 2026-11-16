"""Exit behavior fields shared by creation, updates and manifest serialization."""

from typing import Any

from pydantic import BaseModel


class ExitBehaviorFields(BaseModel):
    unlock_expression: str | None = None
    on_open_exit_script: str | None = None
    on_open_exit_text: str | None = None
    on_exit_used_script: str | None = None
    on_exit_used_text: str | None = None
    on_unlock_success_script: str | None = None
    on_unlock_success_text: str | None = None
    on_unlock_failure_script: str | None = None
    on_unlock_failure_text: str | None = None


EXIT_SCRIPT_FIELDS = tuple(ExitBehaviorFields.model_fields)


def exit_behavior_values(source: Any) -> dict[str, str | None]:
    return {key: (getattr(source, key) or "").strip() or None for key in EXIT_SCRIPT_FIELDS}
