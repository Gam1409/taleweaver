"""Additive, bounded diagnostics for unreviewed RP intervals; never new beliefs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from backend.core.text_evidence import EvidenceSpan

RECOVERY_NOTICE = "NPC analysis paused; RP continued with the last confirmed identity."
RECOVERY_FRAGMENTS = 4


class RecoveryAudit(BaseModel):
    """Durable observer eligibility and progress on the canonical assistant row."""

    model_config = ConfigDict(extra="forbid")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str | None = None
    scene_id: str
    game_minute: int | None = Field(default=None, ge=0)
    actors: dict[str, Annotated[int, Field(ge=0)]] = Field(max_length=20)
    speakers: dict[str, str] = Field(default_factory=dict, max_length=128)
    uncertain_fragments: dict[str, list[EvidenceSpan]] = Field(default_factory=dict, max_length=20)
    unavailable_reason: str | None = Field(default=None, max_length=120)
    unavailable_actors: list[str] = Field(default_factory=list, max_length=20)


class HistoricalObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scene_id: str
    game_minute: int | None = Field(default=None, ge=0)
    evidence_span: EvidenceSpan


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
    failure_detail: str | None = Field(default=None, max_length=1200)


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
