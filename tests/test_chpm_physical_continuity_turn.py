"""Real saved turns deliver the same fact through detours, treatment and resolution."""

import json

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import inference, rendering
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY as CHPM_KEY
from backend.engine.chpm.state import load
from backend.engine.physical_conditions.ledger import apply, read
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_physical_conditions import record
from tests.test_vn_turn_integration import ACTION, final_payload, install_roles, seed_vn


def frame(supplied):
    return json.loads(supplied["psychological_state"]["current_host_observations"][0]["text"])


def manually(state, proposals, label):
    state.entity_states, accepted, errors = apply(
        state.entity_states,
        proposals,
        targets={"LINA"},
        narration="",
        message_id=label,
        session_id=state.session_id,
        minute=state.in_game_time,
        manual=True,
    )
    assert accepted and not errors
    return accepted[0]


async def test_private_injury_survives_twelve_turns_zero_transcript_reload_and_explicit_healing(
    monkeypatch,
):
    roles = ChpmRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        identifier = manually(
            state,
            [record(target_id="LINA", detail="PERSISTENT_PRIVATE_NECK_WOUND")],
            "manual-injury",
        )
        state.entity_states = {
            **state.entity_states,
            CHPM_KEY: KernelState(
                settings=Settings(
                    mode="live", actor_ids=["LINA"], memory_limit=0, failure_policy="strict"
                )
            ).model_dump(),
        }
        await db.commit()
        state_id = state.id
        for _ in range(12):
            events = [
                part async for part in GameTurnManager(db, "session-1", user).process_turn(ACTION)
            ]
            assert final_payload(events)["status"] == "success", "".join(events)
            physical = frame(roles.proposal_inputs[-1])["physical_conditions"]
            assert physical[0]["id"] == identifier and physical[0]["status"] == "active"
            assert "own_physical_conditions" not in roles.proposal_inputs[-1]
            assert "PERSISTENT_PRIVATE_NECK_WOUND" not in json.dumps(
                roles.prompts[-1], ensure_ascii=False, default=str
            )
            assert load(state).memories["LINA"] == []
        pinned_identity = load(state).minds["LINA"].genesis
    async with TestSessionLocal() as db:
        state = await db.get(SessionState, state_id)
        for operation, status in [("treat", "treated"), ("heal", "resolved")]:
            manually(
                state,
                [
                    {
                        "operation": operation,
                        "condition_id": identifier,
                        "evidence": "Explicit debug correction.",
                    }
                ],
                f"manual-{operation}",
            )
            await db.commit()
            events = [
                part async for part in GameTurnManager(db, "session-1", user).process_turn(ACTION)
            ]
            assert final_payload(events)["status"] == "success", "".join(events)
            assert frame(roles.proposal_inputs[-1])["physical_conditions"][0]["status"] == status
        saved = load(state).minds["LINA"]
        assert saved.genesis == pinned_identity
        assert read(state.entity_states).conditions[identifier].status == "resolved"
        assert Mind.model_validate_json(saved.model_dump_json()) == saved
        decision = load(state).actors["LINA"]
        tools = Tools(saved, decision.observation, {})
        assert '"resolved"' in tools.execute(Lookup(tool="inspect_self"))["text"]
        assert roles.chpm_calls == ["perception", "proposal", "validation"] * 14


async def test_explicit_public_resolution_reaches_narrator_and_full_replay_restores_pre_turn_state(
    monkeypatch,
):
    from tests.test_physical_conditions_integration import NARRATION, PROPOSAL, ConditionRoles

    roles = ConditionRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        identifier = manually(state, [record(target_id="LINA", visibility="public")], "record")
        manually(
            state,
            [{"operation": "heal", "condition_id": identifier, "evidence": "Fully healed."}],
            "heal",
        )
        roles.proposals = []
        events = [
            part async for part in GameTurnManager(db, "session-1", user).process_turn(ACTION)
        ]
        assert final_payload(events)["status"] == "success"
        prompt = json.dumps(roles.prompts[-1], ensure_ascii=False, default=str)
        assert "resolved" in prompt and identifier in prompt
        assert "An open neck wound." not in prompt
        progression = next(
            call for call in roles.calls if call[0].startswith("VNProgressionIntent")
        )
        assert '"resolved"' in progression[1][1]
        # A new occurrence during a later turn can be rewound without discarding
        # the earlier, explicitly healed record.
        roles.proposals = [PROPOSAL]
        host = GameTurnManager(db, "session-1", user)
        events = [part async for part in host.process_turn(ACTION)]
        assert final_payload(events)["status"] == "success"
        new_row = next(
            row for row in read(state.entity_states).conditions.values() if row.status == "active"
        )
        roles.proposals = []
        replay = [
            part
            async for part in GameTurnManager(db, "session-1", user).process_turn(
                "ignored", replay_message_id=new_row.origin.message_id
            )
        ]
        assert final_payload(replay)["status"] == "success"
        await db.refresh(state)
        assert list(read(state.entity_states).conditions) == [identifier]
        assert read(state.entity_states).conditions[identifier].status == "resolved"
