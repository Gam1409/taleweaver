"""An actor may add selected steps at submission, within the same command authority."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.proposal_actions import AdditionalActions, approve
from backend.engine.npc_actions.contracts import MAX_ACTIONS, ChangeState, Take
from backend.engine.npc_actions.preview import Draft
from tests.test_npc_action_previews import fixture


def steps(*items, choice="CONTINUE"):
    return AdditionalActions.model_validate({"for_choice": choice, "steps": list(items)})


TAKE = {"tool": "take_item", "item_id": "KEY"}
GIVE = {"tool": "give_item", "item_id": "KEY", "recipient_id": "other"}


def test_combines_selected_steps_in_order_without_mutating_canonical_custody():
    _, scope, draft = fixture()
    approve(draft, "CONTINUE", steps(TAKE, GIVE))
    assert draft.approved
    assert [r.tool for r in draft.requests] == ["take_item", "give_item"]
    assert len({operation.operation_id for operation in draft.operations}) == 2
    assert draft.working_copy()[1].owners["KEY"] == "other"
    assert scope.possessions.owners["KEY"] == "__scene__"


def test_failed_second_step_leaves_the_original_plan_intact_for_one_repair():
    _, _, draft = fixture()
    with pytest.raises(ChpmError, match=r"steps/1"):
        approve(draft, "CONTINUE", steps(TAKE, {**GIVE, "recipient_id": "absent"}))
    assert not draft.approved and not draft.operations and not draft.requests
    approve(draft, "CONTINUE", steps(TAKE, GIVE))
    assert len(draft.requests) == 2


def test_supplement_appends_to_preview_and_rejects_an_unselected_alternative():
    _, _, draft = fixture()
    draft.execute(Take.model_validate(TAKE))
    first = draft.operations[0]
    with pytest.raises(ChpmError, match="for_choice"):
        approve(draft, "REFUSE", steps(GIVE))
    assert draft.operations == [first] and not draft.approved
    approve(draft, "CONTINUE", steps(GIVE))
    assert draft.operations[0] == first and len(draft.operations) == 2


def test_present_but_unobservable_recipient_cannot_be_selected_by_guessing_its_id():
    _, scope, _ = fixture()
    draft = Draft(replace(scope, accessible_ids=scope.accessible_ids - {"other"}))
    with pytest.raises(ChpmError, match=r"steps/1"):
        approve(draft, "CONTINUE", steps(TAKE, GIVE))
    assert not draft.requests and not draft.approved


@pytest.mark.parametrize(
    "invalid",
    [
        [TAKE, GIVE, TAKE],
        [{**TAKE, "actor_id": "@player"}],
        [{"tool": "discard_actions"}],
        [{"tool": "set_pose", "posture": "imaginary"}],
    ],
)
def test_wire_has_no_actor_override_or_unbounded_command_list(invalid):
    with pytest.raises(ValidationError):
        steps(*invalid)


def test_supplement_shares_the_remaining_command_budget_with_staged_steps():
    _, _, draft = fixture()
    assert draft.execute(Take.model_validate(TAKE))["status"] == "staged"
    for index in range(MAX_ACTIONS - 2):
        result = draft.execute(
            ChangeState(
                tool="change_item_state", item_id="KEY", dimension="surface", detail=f"Mark {index}"
            )
        )
        assert result["status"] == "staged"
    original = tuple(draft.operations)
    with pytest.raises(ChpmError, match=r"steps/1: take_item \(action_limit\)"):
        approve(draft, "CONTINUE", steps({"tool": "put_down_item", "item_id": "KEY"}, TAKE))
    assert tuple(draft.operations) == original and not draft.approved
    assert draft.working_copy()[1].owners["KEY"] == "npc"
