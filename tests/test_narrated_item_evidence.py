"""Item rejections explain their actual cause and retain bounded proposal evidence."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.api.routes.adventures.state_checks import state_checks
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_narrated_items import action, run
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn


@pytest.mark.parametrize(
    "proposal,reason",
    [
        (action(evidence="Anna gave the blue shirt away."), "exact contiguous substring"),
        (action(basis="claim"), "Action basis 'claim'"),
    ],
)
def test_quote_mismatch_and_incomplete_action_have_distinct_diagnostics(proposal, reason):
    _, accepted, errors = run([proposal], narration=action().evidence)
    assert not accepted
    assert reason in errors[0]


@pytest.mark.parametrize(
    "count,quote", [(1, "Lina handed the scarf to the traveler."), (6, "X" * 800)]
)
async def test_rejected_proposal_evidence_survives_reload_and_owner_inspection(
    monkeypatch, count, quote
):
    body = "Lina kept her scarf."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", body)

    class RejectedEvidenceRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                return extraction(
                    schema,
                    actions=[
                        ItemAction(
                            item_id=f"SCARF-{index}",
                            source_owner="LINA",
                            destination_owner=PLAYER,
                            disposition="carried",
                            evidence=quote,
                            basis="completed",
                        )
                        for index in range(count)
                    ],
                )
            return await super().structured(*args, **kwargs)

    roles = RejectedEvidenceRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, _, _ = await seed_vn(db)
        inventory = list(avatar.inventory)
        from backend.engine.gameplay.manager import GameTurnManager

        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("I wait.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert avatar.inventory == inventory
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        details = state.entity_states[KEY]["rejected_details"]
        assert len(details) == count
        assert details[0]["basis"] == "completed"
        assert details[0]["evidence"] == quote
        assert details[0]["label"] == "SCARF-0"
        assert "exact contiguous substring" in details[0]["reason"]
        report = await state_checks("session-1", db, user)
        assert report["items"]["rejected_details"] == details
        assert json.loads(json.dumps(details)) == details
    assert len(roles.prompts) == 1


async def test_legacy_item_check_keeps_existing_errors_without_inventing_proposal_details():
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        legacy = {
            "status": "complete",
            "accepted": [],
            "rejected": ["SCARF: No exact evidence of a completed item action."],
        }
        state.entity_states = {**state.entity_states, KEY: legacy}
        await db.commit()
        report = await state_checks("session-1", db, user)
        assert report["items"]["rejected"] == legacy["rejected"]
        assert report["items"]["rejected_details"] == []
        assert state.entity_states[KEY] == legacy


async def test_rejected_proposal_quotes_are_not_exposed_to_another_owner():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: {"rejected_details": [{"evidence": "PRIVATE_REJECTED_PROPOSAL"}]},
        }
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await state_checks("session-1", db, User(id="OTHER_OWNER"))
        assert error.value.status_code == 404
        assert "PRIVATE_REJECTED_PROPOSAL" not in str(error.value.detail)
