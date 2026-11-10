from datetime import datetime

from pydantic import BaseModel, Field

CheckpointTriggerReason = str


class SessionCheckpointResponse(BaseModel):
    id: str
    session_id: str
    message_index: int
    trigger_reason: CheckpointTriggerReason
    pinned: bool = False
    title: str
    created_at: datetime
    turn_number: int | None = Field(default=None, ge=1)
    input_preview: str | None = Field(default=None, max_length=160)

    model_config = {"from_attributes": True}


class RestoreCheckpointResponse(BaseModel):
    status: str
    checkpoint_id: str
    deleted_messages: int
    warnings: list[str] = Field(default_factory=list)
