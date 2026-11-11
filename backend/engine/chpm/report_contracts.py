"""Transmission provenance is separate from an observer's causal interpretation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_HOPS = 16


class ReportHop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: str = Field(min_length=1, max_length=100)
    revision_id: str | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["user", "assistant"]
    observer_id: str = Field(min_length=1, max_length=100)
    speaker_id: str = Field(min_length=1, max_length=100)
    quote: str | None = Field(default=None, min_length=1, max_length=2000)


class ReportLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roots: tuple[str, ...] = Field(min_length=1, max_length=16)
    hops: tuple[ReportHop, ...] = Field(min_length=1, max_length=MAX_HOPS)

    @model_validator(mode="after")
    def distinct(self) -> "ReportLineage":
        if len(self.roots) != len(set(self.roots)):
            raise ValueError("A relayed claim cannot duplicate its evidence roots.")
        keys = [(hop.message_id, hop.observer_id, hop.speaker_id, hop.quote) for hop in self.hops]
        if len(keys) != len(set(keys)):
            raise ValueError("Report provenance cannot repeat the same transmission.")
        return self
