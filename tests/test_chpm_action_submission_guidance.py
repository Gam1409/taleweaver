"""Execution guidance accompanies only the world actions offered on this round."""

from copy import deepcopy

import pytest

from backend.engine.chpm import integrated_request, offered_tools
from tests.test_chpm_action_submission_contract import deliberate, proposal

DEFAULT_SUBMISSION = "Submit this observer's complete proposal for host validation."
ACTION_GUIDANCE = "A candidate message_plan alone does not stage or execute"


def capture(monkeypatch):
    definitions = integrated_request._definitions
    rounds = []

    def recorded(prepared, tools, remaining):
        offered = definitions(prepared, tools, remaining)
        rounds.append((remaining, deepcopy(offered)))
        return offered

    monkeypatch.setattr(integrated_request, "_definitions", recorded)
    return rounds


def submission(offered):
    return next(row["function"] for row in offered if row["function"]["name"] == "submit_decision")


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_offered_actions_put_execution_requirement_on_the_terminal_function(
    monkeypatch, protocol
):
    rounds = capture(monkeypatch)
    _, usage, draft, _, system = await deliberate(
        protocol,
        [[("take_item", {"item_id": "KEY"})], [("submit_decision", proposal())]],
    )

    for remaining, offered in rounds:
        assert remaining > 0
        assert "take_item" in {row["function"]["name"] for row in offered}
        description = submission(offered)["description"]
        assert ACTION_GUIDANCE in description
        assert "call that specific function before submitting" in description
        assert "the later narrator cannot supply omitted commands" in description
        assert "no-action choices need no action call" in description
    assert ACTION_GUIDANCE not in system
    assert "Never decide a player's voluntary response" in system.replace("\n", " ")
    assert draft.approved and len(draft.requests) == 1 and usage.calls == 2


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_only_memory_and_discard_offers_keep_the_original_terminal_description(
    monkeypatch, protocol
):
    definitions = offered_tools.definitions

    def without_world_actions(tools):
        offered = definitions(tools)
        if not tools.actions.requests:
            return offered
        return [
            row for row in offered if row["function"]["name"] in {"inspect_self", "discard_actions"}
        ]

    monkeypatch.setattr(offered_tools, "definitions", without_world_actions)
    rounds = capture(monkeypatch)
    _, usage, draft, _, _ = await deliberate(
        protocol,
        [[("take_item", {"item_id": "KEY"})], [("submit_decision", proposal())]],
    )

    names = {row["function"]["name"] for row in rounds[-1][1]}
    assert names == {"inspect_self", "discard_actions", "submit_decision"}
    assert submission(rounds[-1][1])["description"] == DEFAULT_SUBMISSION
    assert draft.approved and len(draft.requests) == 1 and usage.calls == 2


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_exhausted_action_round_does_not_request_an_unavailable_action(monkeypatch, protocol):
    rounds = capture(monkeypatch)
    _, usage, draft, scope, _ = await deliberate(
        protocol,
        [
            [("take_item", {"item_id": "KEY"})],
            [("put_down_item", {"item_id": "KEY"})],
            [("submit_decision", proposal())],
        ],
    )

    assert [remaining for remaining, _ in rounds] == [2, 1, 0]
    assert [row["function"]["name"] for row in rounds[-1][1]] == ["submit_decision"]
    assert submission(rounds[-1][1])["description"] == DEFAULT_SUBMISSION
    assert draft.approved and len(draft.requests) == 2 and usage.calls == 3
    assert scope.possessions.owners["KEY"] == "__scene__"


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_disabled_action_mode_keeps_the_terminal_description_and_memory_guidance(
    monkeypatch, protocol
):
    rounds = capture(monkeypatch)
    _, usage, draft, _, system = await deliberate(
        protocol, [[("submit_decision", proposal())]], actions=False
    )

    assert submission(rounds[0][1])["description"] == DEFAULT_SUBMISSION
    assert "Submit immediately when current information is sufficient;" in system
    assert ACTION_GUIDANCE not in system
    assert not draft.approved and not draft.requests and usage.calls == 1
