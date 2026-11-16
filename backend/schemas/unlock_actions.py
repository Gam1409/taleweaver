"""Typed payloads shared by the play-agent and HTTP unlock endpoints."""

from pydantic import BaseModel


class ContainerUnlockCodeRequest(BaseModel):
    code: str


class ContainerUnlockItemRequest(BaseModel):
    item_id: str


class ExitUnlockCodeRequest(BaseModel):
    code: str


class ExitUnlockItemRequest(BaseModel):
    item_id: str
