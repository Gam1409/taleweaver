"""Current item properties reach existing NPC equipment views without private values."""

import pytest
from sqlalchemy import select

from backend.engine.physical_conditions.ledger import apply
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.asyncio
async def test_npc_card_projects_current_value_and_public_equipment_properties(
    auth_client, portrait_world
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        report = "The coat is crumpled."
        narration = "You check the coat and confirm that."
        player = ChatMessage(
            id="item-report", session_id=state.session_id, role="user", content=report
        )
        reply = ChatMessage(
            id="item-confirmation", session_id=state.session_id, role="assistant", content=narration
        )
        db.add_all([player, reply])
        await db.flush()
        state.entity_states, accepted, errors = apply(
            state.entity_states,
            [
                dict(
                    operation="record",
                    target_id="COAT",
                    kind="item_state",
                    part="form",
                    detail=report,
                    evidence=narration,
                    player_evidence=report,
                    visibility="public",
                ),
                dict(
                    operation="record",
                    target_id="COAT",
                    kind="item_state",
                    part="inscription",
                    detail="A private inscription.",
                    evidence="A private inscription.",
                    visibility="private",
                ),
            ],
            targets={"COAT"},
            item_targets={"COAT"},
            narration=narration + " A private inscription.",
            message_id=reply.id,
            player_message=(player.id, report),
            session_id=state.session_id,
            minute=50,
        )
        # The reply text and evidence hash must agree, as in a completed real turn.
        reply.content += " A private inscription."
        assert not errors and len(accepted) == 2
        await db.commit()
    response = await auth_client.get(URL)
    assert response.status_code == 200, response.text
    data = response.json()["current_state"]
    coat = next(item for item in data["clothing"]["items"] if item["item_id"] == "COAT")
    assert coat["current_state"] == [dict(dimension="form", detail=report, last_changed_minute=50)]
    condition = next(item for item in data["conditions"]["items"] if item["kind"] == "item_state")
    assert condition["detail"] == report
    assert condition["kind"] == "item_state" and condition["part"] == "form"
    assert "A private inscription." not in str(data)
