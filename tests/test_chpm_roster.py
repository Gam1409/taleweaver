"""Twenty-person casts preserve state and never silently drop direct participants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import capacity, context, perception, roster, runtime
from backend.engine.chpm.schema import KernelState, Perception, Settings
from backend.engine.chpm.state import KEY, load
from tests.test_chpm_kernel import observation
from tests.test_chpm_runtime import manager


def cast(count=20, active=3):
    ids = [f"npc-{number:02}" for number in range(count)]
    settings = Settings(
        mode="live", actor_ids=ids, max_active_npcs=active, max_calls_per_turn=active + 5
    )
    return KernelState(settings=settings), {key: Perception(actor_id=key) for key in ids}


def test_twenty_npcs_retain_focus_and_direct_participants_take_priority():
    state, seen = cast()
    selected = roster.select(state, seen)
    state.last_active.update(dict.fromkeys(selected, 1))
    assert roster.select(state, seen) == selected
    # When the current group leaves, choose previously inactive participants.
    other_scene = {key: value for key, value in seen.items() if key not in selected}
    assert not set(roster.select(state, other_scene)) & set(selected)
    seen["npc-19"].engaged = True
    assert roster.select(state, seen)[0] == "npc-19"
    assert capacity.required_calls(state.settings) == 8
    assert KernelState.model_validate_json(state.model_dump_json()) == state


def test_direct_group_overflow_is_visible_instead_of_silent_sampling():
    state, seen = cast()
    for value in list(seen.values())[:4]:
        value.engaged = True
    with pytest.raises(ValueError, match="directly involves 4"):
        roster.select(state, seen)
    state.settings.max_active_npcs = 20
    state.settings.max_calls_per_turn = 25
    assert len(roster.select(state, seen)) == 20
    assert capacity.required_calls(state.settings) == 25


async def test_runtime_only_prepares_active_characters_and_preserves_saved_inactive_state(
    monkeypatch,
):
    host, prototype = manager()
    state, seen = cast()
    host.state.entity_states[KEY] = state.model_dump()
    actors = [SimpleNamespace(**{**vars(prototype), "id": key, "name": key}) for key in seen]
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    monkeypatch.setattr(context, "observation", AsyncMock(return_value=observation()))
    monkeypatch.setattr(perception, "project", AsyncMock(return_value=seen))
    prepare = AsyncMock()
    monkeypatch.setattr(runtime, "_prepare_actor", prepare)
    before = load(host.state)
    await runtime.prepare(host, "Hello", actors)
    assert prepare.await_count == 3
    turn = runtime.current(host)
    assert len(turn.deferred_names) == 17
    assert "Do not invent new dialogue" in runtime.contract(turn)
    assert load(host.state) == before


def test_legacy_settings_default_to_three_and_cannot_select_twenty_one():
    assert Settings.model_validate({}).max_active_npcs == 3
    with pytest.raises(ValueError):
        cast(21)
