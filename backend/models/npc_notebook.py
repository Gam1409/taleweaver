"""One current private JSON document per owner, session and NPC."""

import uuid6
from sqlalchemy import CheckConstraint, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class NpcNotebook(Base, TimestampMixin):
    __tablename__ = "npc_notebooks"
    __table_args__ = (
        UniqueConstraint("session_id", "npc_id"),
        CheckConstraint("byte_size >= 1 AND byte_size <= 16000000", name="notebook_byte_size"),
        CheckConstraint("revision >= 0", name="notebook_revision"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True
    )
    npc_id: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
