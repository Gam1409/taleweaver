"""Silent agenda changes use explicit null within the existing single repair."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognitive_proposal, inference, proposal_attempt, proposal_edits
from backend.engine.chpm.errors import ProposalRejectedError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.proposal_references import ReferenceDraft
from backend.engine.chpm.schema import Decision, Settings, Usage
from tests.test_chpm_agenda import undertaking
from tests.test_chpm_appraisal import heard
from tests.test_chpm_json_contract import host
from tests.test_chpm_kernel import observation, wire_proposal

PATH = "/candidates/DEFER/agenda_change"


@pytest.fixture
def deferred_change():
    manager = host(None)
    manager.game_id = "session"
    settings = Settings(mode="live", actor_ids=["npc"])
    entries = [undertaking()]
    mind = heard(message="input", text="The bridge is ready. The inspection is complete.")
    prepared = cognitive_proposal.prepare(
        manager,
        settings,
        "npc",
        observation(),
        {},
        entries,
        mind,
        None,
        pinned={},
        pinned_beliefs={},
        focus=(),
        hits=[],
        audit=[],
        notebook=None,
    )
    fragment = next(iter(prepared.references.quotes))
    # Raw modern wire: no legacy fixture adapter may supply a missing choice.
    raw = {
        "reference_scope": prepared.references.scope,
        "choice": {
            "preferred": "CONTINUE",
            "motive_ids": ["goal1"],
            "reason": "Report the completed bridge inspection",
            "continuity": "new",
            "change_basis": [],
        },
        "new_beliefs": [
            {
                "about_id": "@player",
                "domain": "reliability",
                "statement": "The inspection report may be reliable",
                "stance": "support",
                "citations": [{"fragment_id": fragment}],
                "alternatives": [],
                "unknowns": [],
            }
        ],
        "belief_revisions": [],
        "experiences": [],
        "question_gate": None,
        "candidates": {
            "CONTINUE": {
                "message_plan": "Report the completed bridge inspection",
                "preconditions": [],
                "reconsider_if": "The inspection report changes",
                "agenda_change": {"action": "report_done", "entry_id": entries[0].id},
                "motives": [
                    {"motive_id": "goal1", "effect": "supports", "relevance": "Bridge safety"}
                ],
            },
            "DEFER": {
                "message_plan": "Remain silent",
                "preconditions": [],
                "reconsider_if": "A new request arrives",
                "agenda_change": {"action": "goal", "text": "Keep the station informed"},
                "motives": [
                    {"motive_id": "character", "effect": "supports", "relevance": "Wait to speak"}
                ],
            },
        },
    }
    return SimpleNamespace(
        manager=manager,
        model=manager._chpm_model_factory("complex"),
        settings=settings,
        usage=Usage(),
        entries=entries,
        mind=mind,
        prepared=prepared,
        raw=raw,
        checked=[],
    )


async def attempt(environment, edit):
    environment.model.aexecute_simple_task.side_effect = [
        json.dumps(environment.raw),
        json.dumps({"edits": [edit]}),
    ]
    prepared = environment.prepared

    def accept(draft):
        environment.checked.append(draft.model_dump(mode="json"))
        return prepared.accept(draft)

    return await proposal_attempt.request(
        environment.manager,
        environment.settings,
        environment.usage,
        prepared.instruction,
        prepared.payload,
        prepared.schema,
        prepared.identifiers,
        accept,
    )


async def test_defer_hint_reaches_one_real_modern_null_repair_without_changing_other_fields(
    deferred_change,
):
    environment = deferred_change
    before = deepcopy(environment.raw)
    original_mind = environment.mind.model_dump_json()
    entries = deepcopy(environment.entries)

    decision, changed = await attempt(environment, {"op": "replace", "path": PATH, "value": None})

    calls = environment.model.aexecute_simple_task.call_args_list
    feedback = json.loads(calls[1].args[1])["proposal_feedback"]
    assert "silent DEFER" in feedback["error"]
    assert f"Replace {PATH} with null" in feedback["error"]
    assert "keep the field present" in feedback["error"]
    assert feedback["repair_mode"] == "field_edits"
    assert feedback["rejected_proposal"] == ReferenceDraft.model_validate(before).model_dump(
        mode="json"
    )
    expected = deepcopy(feedback["rejected_proposal"])
    expected["candidates"]["DEFER"]["agenda_change"] = None
    assert environment.checked == [feedback["rejected_proposal"], expected]
    assert decision.selected.kind == before["choice"]["preferred"]
    assert decision.choice_preference.model_dump() == before["choice"]
    assert decision.selected.agenda_change.entry_id == entries[0].id
    candidates = {candidate.kind: candidate for candidate in decision.proposal.candidates}
    assert candidates["DEFER"].agenda_change is None
    assert candidates["CONTINUE"] == decision.selected
    assert {kind: items[0].source.id for kind, items in decision.candidate_motives.items()} == {
        "CONTINUE": "goal1",
        "DEFER": "character",
    }
    assert len(changed.snapshot.beliefs) == 1
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    assert environment.mind.model_dump_json() == original_mind
    assert environment.entries == entries and environment.raw == before
    assert [call.kwargs["phase"] for call in calls] == ["proposal", "proposal_repair"]
    assert environment.usage.calls == 2 and environment.usage.proposal_repairs == 1
    assert environment.usage.format_repairs == 0
    for call in calls:
        assert len(call.args[0]) + len(call.args[1]) <= environment.settings.max_input_chars


@pytest.mark.parametrize("operation", ["remove", "replace_parent_without_field"])
async def test_modern_agenda_removal_is_rejected_after_one_repair_without_effects(
    deferred_change, operation
):
    environment = deferred_change
    before = deepcopy(environment.raw)
    original_mind = environment.mind.model_dump_json()
    entries = deepcopy(environment.entries)
    edit = {"op": "remove", "path": PATH}
    if operation == "replace_parent_without_field":
        candidate = deepcopy(environment.raw["candidates"]["DEFER"])
        candidate.pop("agenda_change")
        edit = {"op": "replace", "path": "/candidates/DEFER", "value": candidate}

    with pytest.raises(ProposalRejectedError, match="DEFER.agenda_change.*Field required"):
        await attempt(environment, edit)

    assert environment.model.aexecute_simple_task.await_count == 2
    assert environment.usage.calls == 2 and environment.usage.proposal_repairs == 1
    assert environment.usage.format_repairs == 0
    assert environment.mind.model_dump_json() == original_mind
    assert environment.entries == entries and environment.raw == before


async def test_raw_modern_omission_is_not_filled_before_repair(deferred_change):
    environment = deferred_change
    environment.raw["candidates"]["DEFER"].pop("agenda_change")
    before = deepcopy(environment.raw)
    environment.model.aexecute_simple_task.return_value = json.dumps(environment.raw)

    with pytest.raises(inference.InvalidResponseError, match="DEFER.agenda_change") as rejected:
        await inference.request(
            environment.manager,
            environment.settings,
            environment.usage,
            environment.prepared.instruction,
            environment.prepared.payload,
            environment.prepared.schema,
            "proposal",
            identifiers=environment.prepared.identifiers,
        )

    assert rejected.value.candidate == environment.raw == before
    assert environment.model.aexecute_simple_task.await_count == environment.usage.calls == 1
    assert environment.usage.format_repairs == environment.usage.proposal_repairs == 0


def test_legacy_optional_agenda_field_can_still_be_removed():
    raw = wire_proposal()
    raw["candidates"]["DEFER"]["agenda_change"] = {"action": "goal", "text": "Keep watch"}
    before = deepcopy(raw)
    edit = proposal_edits.Corrections.model_validate({"edits": [{"op": "remove", "path": PATH}]})

    corrected = proposal_edits.apply(raw, edit, Draft)

    assert "agenda_change" not in corrected["candidates"]["DEFER"]
    legacy = Draft.model_validate(corrected)
    assert legacy.candidates["DEFER"].agenda_change is None
    assert raw == before
