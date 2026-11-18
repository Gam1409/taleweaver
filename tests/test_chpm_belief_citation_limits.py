"""Generated fact citations expand without weakening evidence or historical readers."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine import turn_controls
from backend.engine.chpm import agent_beliefs, appraisal, appraisal_context, integrated_request
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.appraisal_contracts import Assessment, Revision
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.replay import restore
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.proposal_references import NewBelief, ReferenceDraft
from backend.engine.chpm.proposal_references import Revision as ReferenceRevision
from backend.engine.chpm.schema import KernelState
from tests.test_chpm_appraisal import heard, proposal
from tests.test_chpm_core import commit, genesis, initial, interpretation, observation
from tests.test_chpm_kernel import observation as turn_observation
from tests.test_chpm_reference_boundaries import prepare, response


def belief_data(count, *, references=False, revision=False):
    raw = {
        "stance": "support",
        "citations": [
            {"fragment_id": f"q{index}"}
            if references
            else {"source_id": f"e{index}", "quote": f"Report {index}."}
            for index in range(count)
        ],
        "alternatives": [],
        "unknowns": [],
    }
    if revision:
        return {**raw, "belief_id": "b1"}
    return {**raw, "about_id": "@player", "domain": "reliability", "statement": "A report"}


@pytest.mark.parametrize("model", [Assessment, Revision, NewBelief, ReferenceRevision])
@pytest.mark.parametrize("count", [1, 2, 7])
def test_fact_proposal_accepts_the_authorized_citation_boundary(model, count):
    parsed = model.model_validate(
        belief_data(
            count,
            references=model in {NewBelief, ReferenceRevision},
            revision=model in {Revision, ReferenceRevision},
        )
    )
    assert len(parsed.citations) == count
    assert model.model_validate_json(parsed.model_dump_json()) == parsed
    schema = model.model_json_schema()
    assert schema["properties"]["citations"]["minItems"] == 1
    assert schema["properties"]["citations"]["maxItems"] == 7


@pytest.mark.parametrize("model", [Assessment, Revision, NewBelief, ReferenceRevision])
@pytest.mark.parametrize("count", [0, 8])
def test_fact_proposal_rejects_empty_or_excess_citations(model, count):
    with pytest.raises(ValidationError):
        model.model_validate(
            belief_data(
                count,
                references=model in {NewBelief, ReferenceRevision},
                revision=model in {Revision, ReferenceRevision},
            )
        )


def prepared_fact(*, revision=False):
    value = None
    for index in range(5):
        value = heard(value, f"history-{index}", f"Bridge report {index} is ready.")
    value = heard(
        value,
        "input",
        " ".join(
            f"Current bridge report detail {index} confirms the crossing." for index in range(12)
        ),
    )
    if revision:
        window = appraisal_context.build(value, current_message_id="input")
        alias, (_, _, text) = next(iter(window.sources.items()))
        value = appraisal.accept(
            value,
            [proposal(citations=[{"source_id": alias, "quote": text[:100]}])],
            window,
            message_id="seeded-belief",
        )[0]
    host, value, prepared = prepare(value=value)
    raw = response(prepared)
    for candidate in raw["candidates"].values():
        candidate["message_plan"] = candidate.pop("intention")
    selectors = [{"fragment_id": key} for key in list(prepared.references.quotes)[:7]]
    assert len(selectors) == 7
    belief = belief_data(7, references=True, revision=revision)
    belief["citations"] = selectors
    if revision:
        belief["belief_id"] = prepared.identifiers["belief_id"][0]
    raw["belief_revisions" if revision else "new_beliefs"] = [belief]
    return host, value, prepared, raw


@pytest.mark.parametrize("revision", [False, True])
def test_seven_visible_fact_citations_reach_native_json_and_saved_interpretations(revision):
    _, before, prepared, raw = prepared_fact(revision=revision)
    original = before.model_dump_json()
    tools = Tools(before, turn_observation(), {})
    native = integrated_request._definitions(prepared, tools, 0)[0]["function"]["parameters"]
    for contract in (native, response_schema(prepared.schema, prepared.identifiers)):
        validator = Draft202012Validator(contract)
        assert validator.is_valid(raw), list(validator.iter_errors(raw))
        excess = deepcopy(raw)
        key = "belief_revisions" if revision else "new_beliefs"
        excess[key][0]["citations"].append(raw[key][0]["citations"][0])
        assert not validator.is_valid(excess)
    _, changed = prepared.accept(prepared.schema.model_validate(raw))
    interpretation = list(events(changed.snapshot))[-1].payload
    assert len(interpretation.citations) == 7
    assert len({(c.record_id, c.quote) for c in interpretation.citations}) == 7
    assert before.model_dump_json() == original
    saved = KernelState(minds={"npc": changed})
    assert KernelState.model_validate_json(saved.model_dump_json()) == saved
    assert Mind.model_validate_json(changed.model_dump_json()) == changed
    projected = agent_beliefs._grounds(Tools(changed, turn_observation(), {}), interpretation)
    assert len(projected["results"]) == 2 and projected["omitted_citations"] == 5
    assert KernelState(minds={"npc": changed}).model_dump_json() == saved.model_dump_json()


@pytest.mark.parametrize("invalid", ["hidden", "foreign_scope", "stale"])
def test_more_fact_citations_do_not_expand_source_or_attempt_authority(invalid):
    host, before, prepared, raw = prepared_fact()
    original = before.model_dump_json()
    if invalid == "hidden":
        raw["new_beliefs"][0]["citations"][-1] = {"fragment_id": "hidden-not-offered"}
    if invalid == "foreign_scope":
        raw["reference_scope"] = "another-window"
    if invalid == "stale":
        turn_controls.begin(host)
    rejected = StaleControlError if invalid == "stale" else ValueError
    with pytest.raises(rejected):
        prepared.accept(prepared.schema.model_validate(raw))
    assert before.model_dump_json() == original


@pytest.mark.parametrize("count", [2, 8, 16])
def test_historical_core_citation_capacity_remains_readable_and_source_checked(count):
    from backend.engine.chpm.core.contracts import Citation

    value = initial(genesis())
    for number in range(1, count + 1):
        value = commit(value, observation(number, root=f"report-{number}"))
    citations = tuple(
        Citation(record_id=f"o{n}", quote="B did not arrive.") for n in range(1, count + 1)
    )
    value = commit(value, interpretation(count + 1, citations=citations))
    assert len(value.evidence[-1].citations) == count
    assert restore(value.model_dump(mode="json"), expected_genesis=genesis()) == value


def test_fact_extension_does_not_raise_emotion_or_choice_evidence_limits():
    schema = ReferenceDraft.model_json_schema()
    assert schema["$defs"]["Experience"]["properties"]["citations"]["maxItems"] == 2
    assert schema["$defs"]["Choice"]["properties"]["change_basis"]["maxItems"] == 2
    assert schema["properties"]["new_beliefs"]["maxItems"] == 2
    assert schema["properties"]["belief_revisions"]["maxItems"] == 2
