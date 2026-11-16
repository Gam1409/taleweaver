"""Explicit connection capacity, independent of model inheritance and sampling."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.core.llm_roles import LLMRole


class ParallelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    max_concurrent: int = Field(default=2, ge=2, le=4, strict=True)

    @property
    def capacity(self) -> int:
        return self.max_concurrent if self.enabled else 1


class ParallelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: dict[LLMRole, ParallelPolicy] = Field(default_factory=dict, max_length=5)


def resolve(settings: dict[str, Any], role: str | None) -> ParallelPolicy | None:
    """An empty legacy profile keeps old scheduling until a role is configured.

    Once configured, unspecified roles are exclusive participants in the same
    endpoint pool. Permissions always belong to the requested role, not its donor.
    """
    policies = ParallelSettings.model_validate(settings.get("parallel_requests") or {}).roles
    if not policies:
        return None
    return next((policy for key, policy in policies.items() if key == role), ParallelPolicy())


def npc_capacity(user: Any, role: str, session_limit: int) -> int:
    policy = resolve(getattr(user, "llm_settings", None) or {}, role)
    return min(session_limit, policy.capacity) if policy is not None else session_limit
