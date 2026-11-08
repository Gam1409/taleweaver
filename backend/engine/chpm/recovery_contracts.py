"""Additive, bounded diagnostics for unreviewed RP intervals; never new beliefs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class SimplifiedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_id: str
    reply_id: str
    reply_revision: str | None = None
    reply_hash: str
    reason: str = Field(max_length=80)
    actor_ids: list[str] = Field(default_factory=list, max_length=20)
    proposal_feedback: list[Annotated[str, Field(max_length=600)]] = Field(
        default_factory=list, max_length=2
    )


class RecoveryState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consecutive_failures: int = Field(default=0, ge=0)
    cooldown_remaining: int = Field(default=0, ge=0, le=3)
    pending_gap_turns: int = Field(default=0, ge=0)
    total_simplified_turns: int = Field(default=0, ge=0)
    last_gap_revision: int = Field(default=0, ge=0)
    # The last verified observer cursor makes pre-gap feelings explicitly historical.
    gap_cursors: dict[str, int] = Field(default_factory=dict, max_length=32)
    # This is a diagnostic window, not the canonical conversation or core journal.
    recent: list[SimplifiedReply] = Field(default_factory=list, max_length=8)
