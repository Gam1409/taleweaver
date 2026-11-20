"""Optional alternatives cannot veto a separate, eligible, personally grounded decision."""

from copy import deepcopy

import pytest

from backend.engine.chpm import motivation
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_chpm_motivation import candidates, catalogue, motive
from tests.test_npc_two_phase_turn import (
    CUP,
    PLAYER,
    TAKE,
    CupRoles,
    assert_committed,
    reload,
    seed,
)


def proposal():
    body = candidates().model_dump(mode="json")
    options = body["candidates"]
    options["CLARIFY"] = deepcopy(options["DEFER"])
    options["DEFER"]["motives"] = [motive("character", "tension")]
    options["CONTINUE"] = deepcopy(options["DEFER"])
    body["choice"] = {
        "preferred": "ACCEPT",
        "motive_ids": ["goal1"],
        "reason": "Inspect the bridge.",
        "continuity": "new",
    }
    return body


def test_only_unsupported_alternatives_are_omitted_in_two_phase():
    raw = GroundedProposal.model_validate(proposal())
    before = raw.model_dump()
    assert set(motivation.resolve(raw, catalogue(), omit_unsupported_alternatives=True)) == {
        "ACCEPT",
        "CLARIFY",
    }
    assert raw.model_dump() == before
    with pytest.raises(ChpmError, match="lacks a supporting"):
        motivation.resolve(raw, catalogue())


@pytest.mark.parametrize(
    "problem",
    [
        "preferred",
        "too_few",
        "foreign_id",
        "duplicate",
        "gate_branch",
        "blocked_choice",
        "ineligible_clarify",
    ],
)
def test_unsafe_omissions_leave_the_proposal_rejected(problem):
    body = proposal()
    opts = body["candidates"]
    if problem == "preferred":
        body["choice"]["preferred"] = "DEFER"
    elif problem == "too_few":
        del opts["CLARIFY"]
    elif problem == "foreign_id":
        opts["CONTINUE"]["motives"] = [motive("unknown", "tension")]
    elif problem == "duplicate":
        opts["DEFER"]["motives"] *= 2
    elif problem == "ineligible_clarify":
        body["choice"]["preferred"] = "CLARIFY"
    else:
        opts["INITIATE"] = opts.pop("CONTINUE")
        opts["INITIATE"]["motives"] = [motive("character")]
        branches = ("DEFER", "INITIATE") if problem == "gate_branch" else ("ACCEPT", "INITIATE")
        body["question_gate"] = {
            "kind": "external_fact",
            "missing_fact": "Can the bridge open?",
            "branches": [
                {"answer": answer, "action": kind}
                for answer, kind in zip(("yes", "no"), branches, strict=True)
            ],
        }
    with pytest.raises(ChpmError):
        motivation.resolve(
            GroundedProposal.model_validate(body), catalogue(), omit_unsupported_alternatives=True
        )


class AlternateRoles(CupRoles):
    invalid_agenda = False

    def answer(self, payload, functions, phase, kwargs):
        result = super().answer(payload, functions, phase, kwargs)
        if phase != "npc_execution" and payload["actor_id"] == "MILA":
            options = result[0][1]["candidates"]
            options["CLARIFY"] = deepcopy(options["DEFER"])
            options["DEFER"]["motives"] = [motive("character", "tension")]
            options["CONTINUE"] = deepcopy(options["DEFER"])
            if self.invalid_agenda:
                options["DEFER"]["agenda_change"] = {"action": "goal", "text": "Repair the cup."}
        return result


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_second_npc_keeps_choice_and_step_after_first_uses_shared_repair(
    monkeypatch, protocol
):
    roles = AlternateRoles([TAKE], wrong_once=True)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=True)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert_committed(events)
        assert len(roles.choices) == 2 and len(roles.executions) == 3
    async with TestSessionLocal() as db:
        _, manager, possessions = await reload(db, session_id, user_id)
        saved = load(manager.state)
        assert saved.usage.proposal_repairs == 1
        second = saved.actors["MILA"]
        assert second.selected.kind == second.choice_preference.preferred == "REFUSE"
        assert set(second.candidate_motives) == {"REFUSE", "CLARIFY"}
        assert any(
            "CONTINUE" in reason and "DEFER" in reason for reason in second.selection_reasons
        )
        (outcome,) = second.last_publication.operations
        assert (outcome.tool, outcome.item_id, outcome.status) == ("take_item", CUP, "blocked")
        assert possessions.owners[CUP] == "LINA"


async def test_unselected_unsupported_plan_cannot_hide_invalid_agenda_change(monkeypatch):
    roles = AlternateRoles([TAKE], wrong_once=True)
    roles.invalid_agenda = True
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json", pair=True)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert any(event.startswith("event: error") for event in events)
        assert not any(event.startswith(("event: chunk", "event: final")) for event in events)
        assert len(roles.executions) == 2  # Only the first NPC's attempts.
    async with TestSessionLocal() as db:
        _, manager, possessions = await reload(db, session_id, user_id)
        assert possessions.owners[CUP] == "__scene__"
        assert not load(manager.state).actors
