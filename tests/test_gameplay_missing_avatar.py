"""Incomplete saved sessions must fail before snapshot processing mutates state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes.adventures import gameplay


@pytest.mark.asyncio
async def test_chat_snapshot_requires_avatar_before_writing_or_scheduling(monkeypatch):
    user = SimpleNamespace(id="owner")
    state = SimpleNamespace(
        session=SimpleNamespace(user_id="owner"), template_id="template", avatar_id="missing"
    )
    monkeypatch.setattr(
        gameplay.AdventureLogic, "resolve_session_state", AsyncMock(return_value=state)
    )
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock())
    build_map = AsyncMock()
    schedule = MagicMock()
    monkeypatch.setattr(gameplay, "build_session_map", build_map)
    monkeypatch.setattr(gameplay, "schedule_npc_journal", schedule)

    with pytest.raises(HTTPException) as error:
        await gameplay.get_chat_history(
            "session", include_full_world=False, db=db, current_user=user
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Avatar not found."
    db.commit.assert_not_awaited()
    build_map.assert_not_awaited()
    schedule.assert_not_called()
