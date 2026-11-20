"""The actor sees the host's eligible physical commands while choosing its next step."""

import pytest

from backend.engine.visual_novel.config import read_settings, write_settings
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_two_phase_turn import PLAYER, CupRoles, assert_committed, seed


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("staging", [False, True])
async def test_choice_lists_only_supported_actions_even_on_the_final_lookup_round(
    monkeypatch, protocol, staging
):
    roles = CupRoles([])
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=False)
        write_settings(state, read_settings(state).model_copy(update={"scene_staging": staging}))
        await db.commit()
        _, events = await run(db, user, PLAYER)

    assert_committed(events)
    [(payload, functions)] = roles.choices
    eligible = payload["available_physical_commands"]
    assert {"take_item", "give_item", "interact"} <= set(eligible)
    assert ("approach" in eligible) == staging
    assert ("set_pose" in eligible) == staging
    assert "discard_actions" not in eligible
    assert set(functions) == {"submit_decision"}
    assert roles.executions == []
