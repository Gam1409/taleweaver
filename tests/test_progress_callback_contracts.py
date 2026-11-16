"""Progress observers may be synchronous or asynchronous without aborting work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.adventure_generator_service import AdventureGeneratorService
from backend.engine.rule_engine import AdventureGenerationRequest
from backend.models.user import User


def observer(asynchronous, messages):
    async def async_observer(message):
        messages.append(message)

    return async_observer if asynchronous else messages.append


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_system_notification_accepts_both_callback_kinds(asynchronous):
    messages = []
    manager = SimpleNamespace(_save_chat_message=AsyncMock(), db=SimpleNamespace(flush=AsyncMock()))
    await GameTurnManager._emit_system_message(manager, "Ready", observer(asynchronous, messages))
    assert messages == ["Ready"]
    manager._save_chat_message.assert_awaited_once_with("system", "Ready")
    manager.db.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_generation_progress_callbacks(asynchronous, fails, monkeypatch):
    messages = []
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), refresh=AsyncMock())

    async def generate(*args, status_callback, **kwargs):
        await status_callback("Generating scenes")
        if fails:
            raise ValueError("Generation failed")

    monkeypatch.setattr(
        "backend.engine.adventure_generator_service.WorldGenerator.generate_world", generate
    )
    request = AdventureGenerationRequest(title="Test", prompt="A small world")
    operation = AdventureGeneratorService.generate_adventure(
        db, User(id="test-user"), request, observer(asynchronous, messages)
    )
    if fails:
        with pytest.raises(ValueError, match="Generation failed"):
            await operation
    else:
        assert await operation
    template = db.add.call_args.args[0]
    assert template.creation_status == ("Failed" if fails else "Ready")
    assert messages == [
        "Initializing adventure generation...",
        "Generating scenes",
        "Adventure generation failed: Generation failed"
        if fails
        else "Adventure generation complete. Finalizing...",
    ]
