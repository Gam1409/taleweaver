"""Debug command dispatch preserves session mutations and control markers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.debug_engine import DebugEngine
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState


@pytest.mark.parametrize(
    ("command", "enabled", "marker"),
    [
        ("on", True, "[DEBUG_LOG_ON]"),
        ("log on", True, "[DEBUG_LOG_ON]"),
        ("off", False, "[DEBUG_LOG_OFF]"),
        ("log off", False, "[DEBUG_LOG_OFF]"),
    ],
)
async def test_debug_log_aliases(command, enabled, marker):
    state = SimpleNamespace(adventure_id="template", scene_id="scene", is_debug_enabled=not enabled)
    response = await DebugEngine.handle_debug_command(None, state, command)
    assert response.startswith(marker)
    assert state.is_debug_enabled is enabled


@pytest.mark.parametrize("command", ["", "unknown", "log", "log invalid"])
async def test_unknown_or_incomplete_command_returns_usage(command):
    state = SimpleNamespace(adventure_id="template", scene_id="scene", is_debug_enabled=False)
    response = await DebugEngine.handle_debug_command(None, state, command)
    assert response.startswith("DEBUG USAGE:")
    assert state.is_debug_enabled is False


async def test_debug_delete_item_matches_id_or_key_without_removing_other_items():
    state = SimpleNamespace(adventure_id="template", scene_id="scene")
    avatar = Avatar(name="Hero", inventory=[{"id": "target"}, {"key": "target"}, {"id": "keep"}])
    response = await DebugEngine.handle_debug_command(
        None, state, "delete_item target", avatar=avatar
    )
    assert response == "DEBUG: Item 'target' removed from inventory."
    assert avatar.inventory == [{"id": "keep"}]


async def test_debug_victory_completes_only_main_quests_without_committing():
    original = [
        {"id": "main", "is_main": True, "status": "open"},
        {"id": "side", "is_main": False, "status": "open"},
    ]
    state = SessionState(quests=original)
    db = AsyncMock()
    response = await DebugEngine.handle_debug_command(db, state, "game_won")
    assert response.startswith("[TRIGGER_GAME_COMPLETED]")
    assert state.quests[0]["status"] == "completed"
    assert state.quests[1]["status"] == "open"
    assert original[0]["status"] == "open"
    db.commit.assert_not_awaited()
