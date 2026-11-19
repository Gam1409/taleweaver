"""One formation repair sees independent faults before any chosen action executes."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import appraisal_context, cognition, inference, proposal_repair
from backend.engine.chpm.errors import ProposalRejectedError
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_reference_fixture import response as reference_response
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_agent_tools import current
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import proposed
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_reference_boundaries import prepare, response


def history():
    value = heard(message="old", text="Have you studied the pattern?")
    return current(heard(value, message="input", text="If you agree, hand over the coat."))


def draft(value):
    window = appraisal_context.build(value, current_message_id="input")
    aliases = {source.message_id: alias for alias, (_, source, _) in window.sources.items()}
    original = wire_proposal()
    original["candidates"]["CONTINUE"]["intention"] = "Remove my coat and hand it over voluntarily."
    original["candidates"]["CONTINUE"]["motives"] = [
        {
            "motive_id": identifier,
            "effect": "supports",
            "relevance": "A reason to consider my own next step.",
        }
        for identifier in (
            "goal1",
            "character",
            f"report-{aliases['old']}",
            f"report-{aliases['input']}",
        )
    ]
    original["candidates"]["DEFER"]["motives"][0]["motive_id"] = "unavailable-motive"
    original["experiences"] = [
        proposed(
            dimension="interest",
            about_id=None,
            citations=[{"source_id": aliases["old"], "quote": "Have you studied the pattern?"}],
        ).model_dump(mode="json"),
        proposed(
            channel="need_satisfaction",
            dimension="autonomy",
            about_id=None,
            citations=[
                {"source_id": aliases["input"], "quote": "If you agree, hand over the coat."}
            ],
        ).model_dump(mode="json"),
    ]
    return original


class RepairModel(NativeModel):
    def __init__(self, original, *, fix_experience=True):
        super().__init__([turn(call("decision", "submit_decision", original))])
        self.original = original
        self.fix_experience = fix_experience
        self.feedback = None

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        self.json_requests.append((system, content, kwargs))
        payload = json.loads(content)
        if kwargs.get("phase") != "proposal_repair":
            value = self.original
            if kwargs.get("phase") == "integrated_decision":
                value = {"requests": [{"name": "submit_decision", "arguments": value}]}
            return reference_response(json.dumps(value), payload)
        self.feedback = payload["proposal_feedback"]
        issues = [i for g in self.feedback["recommended_repair_groups"] for i in g["issues"]]
        assert {"too_long", "motive_unavailable", "experience_current_trigger"} <= {
            item["type"] for item in issues
        }
        stale = next(item for item in issues if item["type"] == "experience_current_trigger")
        assert stale["path"] == "/experiences/0/citations"
        assert stale["category"] == "formation"
        rejected = self.feedback["rejected_proposal"]
        changes = [
            ("/candidates/CONTINUE/motives", rejected["candidates"]["CONTINUE"]["motives"][:1]),
            (
                "/candidates/DEFER/motives",
                [{"motive_id": "character", "effect": "supports", "relevance": "Choose my pace."}],
            ),
        ]
        if self.fix_experience:
            changes.append(("/experiences", rejected["experiences"][1:]))
        return corrections(*changes)


async def deliberate(model, value, protocol):
    settings = Settings(
        mode="live",
        actor_ids=["npc"],
        workflow="integrated",
        agent_steps=0 if protocol == "staged" else 2,
        tool_protocol="json" if protocol == "staged" else protocol,
    )
    usage = Usage()
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    result = await cognition.deliberate(host, settings, usage, "npc", observation(), {}, [], value)
    return result, usage


@pytest.mark.parametrize("protocol", ["native", "json", "staged"])
async def test_structural_motive_and_stale_experience_faults_share_the_single_repair(protocol):
    value = history()
    original = draft(value)
    before, unchanged = value.model_dump_json(), deepcopy(original)
    model = RepairModel(original)
    (decision, changed), usage = await deliberate(model, value, protocol)
    assert decision.selected.intention == original["candidates"]["CONTINUE"]["intention"]
    assert decision.choice_preference.preferred == original["choice"]["preferred"]
    assert len(changed.snapshot.experiences) == 1
    assert changed.snapshot.experiences[0].channel == "need_satisfaction"
    assert value.model_dump_json() == before and original == unchanged
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert len(model.requests) + len(model.json_requests) == 2


async def test_an_unrepaired_experience_remains_a_formation_failure_without_an_extra_call():
    value = history()
    model = RepairModel(draft(value), fix_experience=False)
    before = value.model_dump_json()
    with pytest.raises(ProposalRejectedError) as caught:
        await deliberate(model, value, "native")
    assert caught.value.failure_stage == "proposal_formation"
    assert "formation" in caught.value.failure_categories
    assert any(i["type"] == "experience_current_trigger" for i in caught.value.grounding_issues)
    assert len(model.requests) + len(model.json_requests) == 2
    assert value.model_dump_json() == before


@pytest.mark.parametrize("fault", ["historical", "foreign_reference", "foreign_motive"])
def test_diagnosis_uses_only_the_current_observers_exact_grounding(fault):
    value = history()
    _, _, prepared = prepare(value=value)
    candidate = response(prepared)
    old = next(key for key, quote in prepared.references.quotes.items() if "studied" in quote.quote)
    citation = {"fragment_id": old}
    personal = ["character"]
    if fault == "foreign_reference":
        citation = {"fragment_id": "foreign-observer-fragment"}
    if fault == "foreign_motive":
        personal = ["another-observers-goal"]
    candidate["experiences"] = [
        {
            **proposed(about_id=None).model_dump(mode="json"),
            "citations": [citation],
            "personal_motive_ids": personal,
        }
    ]
    before = value.model_dump_json(), deepcopy(candidate)
    errors = prepared.diagnose(candidate)
    assert any(error["loc"][:2] == ("experiences", 0) for error in errors)
    assert any(
        error["category"] == ("formation" if fault == "historical" else "forbidden_knowledge")
        for error in errors
    )
    assert (value.model_dump_json(), candidate) == before


def test_all_independent_faults_in_one_experience_are_reported_without_new_knowledge():
    value = history()
    _, _, prepared = prepare(value=value)
    candidate = response(prepared)
    old = next(key for key, quote in prepared.references.quotes.items() if "studied" in quote.quote)
    candidate["experiences"] = [
        {
            **proposed(about_id="unobserved-person").model_dump(mode="json"),
            "citations": [{"fragment_id": old}],
            "personal_motive_ids": ["unavailable-personal-motive"],
        }
    ]
    errors = prepared.diagnose(candidate)
    assert {error["type"] for error in errors} == {
        "experience_subject",
        "experience_personal_basis",
        "experience_current_trigger",
    }
    assert {error["category"] for error in errors} == {"formation", "forbidden_knowledge"}
    candidate["experiences"][0]["citations"] = [{"fragment_id": "foreign-fragment"}]
    errors = prepared.diagnose(candidate)
    assert {error["type"] for error in errors} == {
        "experience_subject",
        "experience_personal_basis",
        "experience_visible_source",
    }
    assert {error["category"] for error in errors} == {"forbidden_knowledge"}
    candidate["reference_scope"] = "another-observers-window"
    errors = prepared.diagnose(candidate)
    assert [error["type"] for error in errors] == ["grounding_reference_scope"]
    assert errors[0]["category"] == "forbidden_knowledge"


def test_experience_shape_error_does_not_hide_its_independently_known_stale_source():
    _, _, prepared = prepare(value=history())
    candidate = response(prepared)
    old = next(key for key, quote in prepared.references.quotes.items() if "studied" in quote.quote)
    candidate["experiences"] = [
        {
            **proposed(about_id=None).model_dump(mode="json"),
            "citations": [{"fragment_id": old}],
            "explanation": "x" * 181,
        }
    ]
    before = deepcopy(candidate)
    errors = prepared.diagnose(candidate)
    assert any(error["type"] == "experience_current_trigger" for error in errors)
    assert candidate == before


def test_replaying_same_grounding_cannot_intensify_an_existing_estimate():
    _, _, prepared = prepare(value=history())
    candidate = response(prepared)
    current = next(
        key for key, quote in prepared.references.quotes.items() if "hand over" in quote.quote
    )
    candidate["experiences"] = [
        {
            **proposed(about_id=None).model_dump(mode="json"),
            "citations": [{"fragment_id": current}],
        }
    ]
    _, changed = prepared.accept(prepared.schema.model_validate(candidate))
    before = changed.model_dump_json()
    _, _, replay = prepare(value=changed)
    candidate = response(replay)
    current = next(
        key for key, quote in replay.references.quotes.items() if "hand over" in quote.quote
    )
    candidate["experiences"] = [
        {
            **proposed(about_id=None, level="high").model_dump(mode="json"),
            "citations": [{"fragment_id": current}],
        }
    ]
    errors = replay.diagnose(candidate)
    assert [error["type"] for error in errors] == ["experience_transition"]
    assert errors[0]["category"] == "formation"
    assert changed.model_dump_json() == before


@pytest.mark.parametrize("field", ["new_beliefs", "belief_revisions"])
def test_forbidden_appraisal_memory_is_distinct_from_a_physical_owner_conflict(field):
    value = history()
    _, _, prepared = prepare(value=value)
    candidate = response(prepared)
    candidate[field] = [
        {
            "stance": "support",
            "citations": [{"fragment_id": "unavailable-fragment"}],
            "alternatives": [],
            "unknowns": [],
            **(
                {
                    "about_id": "@player",
                    "domain": "reliability",
                    "statement": "The report may be reliable.",
                }
                if field == "new_beliefs"
                else {"belief_id": "unavailable-belief"}
            ),
        }
    ]
    errors = prepared.diagnose(candidate)
    assert {error["type"] for error in errors} == (
        {"appraisal_visible_source"}
        if field == "new_beliefs"
        else {"appraisal_visible_source", "appraisal_belief"}
    )
    assert {error["category"] for error in errors} == {"forbidden_knowledge"}
    old = next(key for key, quote in prepared.references.quotes.items() if "studied" in quote.quote)
    candidate[field][0]["citations"] = [{"fragment_id": old}]
    errors = prepared.diagnose(candidate)
    if field == "belief_revisions":
        assert errors[0]["type"] == "appraisal_belief"
        assert errors[0]["category"] == "forbidden_knowledge"
    else:
        assert errors == []  # Own accessible historical evidence remains available to beliefs.


def test_complete_grounding_diagnostics_survive_the_fitting_full_response_fallback():
    value = history()
    _, _, prepared = prepare(value=value)
    candidate = response(prepared)
    old = next(key for key, quote in prepared.references.quotes.items() if "studied" in quote.quote)
    candidate["experiences"] = [
        {**proposed(about_id=None).model_dump(mode="json"), "citations": [{"fragment_id": old}]}
    ]
    # Nine independent top-level extras exceed the existing eight-edit limit.
    # The original full-object fallback must still carry the independent source fault.
    candidate.update({f"extra{index}": True for index in range(9)})
    errors = prepared.diagnose(candidate)
    context = {"required_identity": "Keep this observer's identity and evidence."}
    options = {"instruction": "Use the schema.", "identifiers": prepared.identifiers}
    full = proposal_repair.payload_for(
        context,
        prepared.schema,
        "Invalid formation.",
        candidate,
        limit=64000,
        grounding_errors=errors,
        **options,
    )
    size = sum(
        map(
            len,
            inference.compose(options["instruction"], full, prepared.schema, prepared.identifiers),
        )
    )
    result = proposal_repair.prepare(
        context,
        prepared.schema,
        "Invalid formation.",
        candidate,
        limit=size,
        grounding_errors=errors,
        **options,
    )
    assert result.original is None
    assert (
        result.payload["proposal_feedback"]["grounding_errors"][0]["type"]
        == "experience_current_trigger"
    )
    assert result.payload["required_identity"] == context["required_identity"]
    assert (
        sum(
            map(
                len,
                inference.compose(
                    options["instruction"], result.payload, prepared.schema, prepared.identifiers
                ),
            )
        )
        == size
    )
