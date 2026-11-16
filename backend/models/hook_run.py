"""Durable outcome for a hook at a particular player-turn boundary."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class HookRun(Base, TimestampMixin):
    __tablename__ = "hook_runs"
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    boundary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hook_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
