"""Publication feedback is bounded host data, separate from intentions and current state."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, update

from backend.engine.chpm import cognition
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_kernel import decision
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_action_empty_turn import EmptyPlanRoles


def test_legacy_decision_has_no_publication_acknowledgment_field_in_saved_shape():
    value = decision()
    assert "last_publication" not in value.model_dump(mode="json")
    assert value.last_publication is None


@pytest.mark.parametrize("count", [0, 16, 17])
def test_publication_acknowledgment_matches_existing_command_capacity(count):
    from backend.engine.npc_actions.acknowledgment import PublicationAcknowledgment

    raw = {
        "attempt_id": "attempt",
        "operations": [
            {"operation_id": f"op-{index}", "tool": "take_item", "status": "applied"}
            for index in range(count)
        ],
    }
    if count == 17:
        with pytest.raises(ValidationError):
            PublicationAcknowledgment.model_validate(raw)
        return
    assert len(PublicationAcknowledgment.model_validate(raw).operations) == count


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "staged"},
        {"status": "success"},
        {"tool": "run_code"},
        {"reason_code": "Private owner diagnostics"},
        {"effect": {"item_id": "OTHER_PRIVATE_ITEM"}},
    ],
)
def test_feedback_cannot_carry_preview_authority_free_diagnostics_or_effects(changes):
    from backend.engine.npc_actions.acknowledgment import PublicationAcknowledgment

    with pytest.raises(ValidationError):
        PublicationAcknowledgment.model_validate(
            {
                "attempt_id": "attempt",
                "operations": [
                    {"operation_id": "op", "tool": "take_item", "status": "applied", **changes}
                ],
            }
        )


def test_feedback_cannot_repeat_an_operation_or_hide_a_success_as_a_refusal():
    from backend.engine.npc_actions.acknowledgment import PublicationAcknowledgment

    row = {"operation_id": "op", "tool": "take_item", "status": "applied"}
    for rows in ([row, row], [{**row, "reason_code": "stale"}]):
        with pytest.raises(ValidationError):
            PublicationAcknowledgment.model_validate({"attempt_id": "attempt", "operations": rows})


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("input_cap", [24000, 34500, 64000])
async def test_real_next_decision_feedback_and_exact_input_admission(
    monkeypatch, caplog, protocol, input_cap
):
    roles = EmptyPlanRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        kernel.settings.max_input_chars = input_cap
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()

        first, events = await run(db, user, ACTION)
        if input_cap == 24000:
            # The complete existing wire schema exceeds 24k before cognition.
            # Feedback must preserve admission and the previous confirmed state.
            assert any(event.startswith("event: error") for event in events), "".join(events)
            assert "configured size limit" in caplog.text
            await db.refresh(state)
            assert load(state) == kernel
            assert len(roles.chpm_calls) == 1
            return
        assert any(event.startswith("event: final") for event in events), "".join(events)
        saved = load(first.state)
        assert saved.actors["LINA"].last_publication.operations == ()
        assert saved.usage.calls == 3
        first_input = saved.actors["LINA"].observation.message_id
        first_reply = saved.actors["LINA"].reply_id
        assert "previous_action_results_not_current_state" not in roles.proposal_inputs[0]

        second, events = await run(db, user, "I continue the discussion.")
        assert any(event.startswith("event: final") for event in events), "".join(events)
        supplied = roles.proposal_inputs[-1]["previous_action_results_not_current_state"]
        assert supplied["meaning"] == "historical_publication_acknowledgment_not_current_state"
        assert supplied["source_input_id"] == first_input
        assert supplied["source_reply_id"] == first_reply
        assert supplied["operations"] == []
        assert "effect" not in json.dumps(supplied)
        assert load(second.state).settings.max_input_chars == input_cap
        assert load(second.state).usage.calls == 3
        assert len(roles.chpm_calls) == 6


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_existing_schema_already_exceeds_24k_without_feedback(monkeypatch, caplog, protocol):
    from backend.engine.npc_actions import acknowledgment

    async def unavailable(*_args):
        return None

    monkeypatch.setattr(acknowledgment, "context", unavailable)
    roles = EmptyPlanRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        kernel.settings.max_input_chars = 24000
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        _, events = await run(db, user, ACTION)
        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert "configured size limit" in caplog.text
        await db.refresh(state)
        assert load(state) == kernel
        assert len(roles.chpm_calls) == 1


@pytest.mark.parametrize("fault", ["edit", "delete"])
@pytest.mark.parametrize("source", ["input", "reply"])
async def test_source_changed_during_existing_cognitive_call_prevents_publication(
    monkeypatch, caplog, source, fault
):
    roles = EmptyPlanRoles()
    install(monkeypatch, roles)
    original = cognition.deliberate
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        kernel = load(state)
        kernel.settings.action_tools = True
        kernel.settings.max_input_chars = 64000
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        first, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        previous = load(first.state)
        decision = previous.actors["LINA"]
        source_id = decision.reply_id if source == "reply" else decision.observation.message_id

        async def changed(*args, **kwargs):
            assert "previous_action_results_not_current_state" in args[5]
            result = await original(*args, **kwargs)
            statement = (
                delete(ChatMessage).where(ChatMessage.id == source_id)
                if fault == "delete"
                else update(ChatMessage)
                .where(ChatMessage.id == source_id)
                .values(content="The old source was edited.")
            )
            await args[0].db.execute(statement)
            return result

        monkeypatch.setattr(cognition, "deliberate", changed)
        _, events = await run(db, user, "I continue the discussion.")
        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert "acknowledgment source changed" in caplog.text
        assert not any(event.startswith("event: final") for event in events)
        assert len(roles.reviews) == 1
        await db.refresh(state)
        assert load(state) == previous
