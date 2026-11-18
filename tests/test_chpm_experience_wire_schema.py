"""Experience wire constraints agree with the unchanged canonical state owner."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.core.llm_schema_projection import project
from backend.engine.chpm import integrated_request, json_contract, proposal_references
from backend.engine.chpm.core.contracts import ExperienceValue
from backend.engine.chpm.host_state import Mind, record
from tests import test_chpm_action_submission_contract as submission_fixture
from tests.test_chpm_action_submission_contract import deliberate, proposal
from tests.test_chpm_host_state import source
from tests.test_chpm_json_schema_references import payload, resolved, tool
from tests.test_chpm_reference_boundaries import prepare, response

CHANNEL_CASES = [
    ("affect", "interest", None, True),
    ("affect", "anger", "@player", True),
    ("need_satisfaction", "autonomy", None, True),
    ("need_frustration", "relatedness", None, True),
    ("need_satisfaction", "autonomy", "@player", False),
    ("need_frustration", "safety", "@player", False),
    ("affect", "autonomy", None, False),
    ("need_satisfaction", "joy", None, False),
    ("need_frustration", "interest", None, False),
    ("affect", "interest", "foreign", False),
]


def experience(channel="affect", dimension="interest", about_id=None):
    return {
        "channel": channel,
        "dimension": dimension,
        "about_id": about_id,
        "level": "moderate",
        "citations": [{"fragment_id": "q1"}],
        "personal_motive_ids": ["character"],
        "explanation": "The observation matters to my own purpose.",
        "alternatives": [],
        "unknowns": [],
    }


def schema_for(transport):
    schema = json_contract.response_schema(
        proposal_references.Experience,
        {"about_id": ["@player"], "fragment_id": ["q1"], "personal_motive_ids": ["character"]},
    )
    if transport == "decoder":
        return project(schema).schema
    if transport == "portable":
        body = payload(tool("submit_decision", schema))
        return resolved(body, body["functions"][0]["parameters"])
    return schema


@pytest.mark.parametrize("transport", ["native", "portable", "decoder"])
@pytest.mark.parametrize("channel,dimension,about_id,valid", CHANNEL_CASES)
def test_wire_transport_exposes_channel_dimension_and_target_invariants(
    transport, channel, dimension, about_id, valid
):
    validator = Draft202012Validator(schema_for(transport))
    assert validator.is_valid(experience(channel, dimension, about_id)) is valid


def test_need_diagnostic_identifies_the_field_and_correction_without_reinterpreting_thoughts():
    with pytest.raises(ValidationError, match="about_id must be null"):
        proposal_references.Experience.model_validate(
            experience("need_satisfaction", "autonomy", "@player")
        )


@pytest.mark.parametrize("channel", ["need_satisfaction", "need_frustration"])
def test_real_reference_materialization_and_reload_keep_the_observer_need(channel):
    _host, original, prepared = prepare()
    raw = response(prepared)
    selected = experience(channel, "competence")
    selected["citations"] = [{"fragment_id": next(iter(prepared.references.quotes))}]
    raw["experiences"] = [selected]
    raw = prepared.schema.model_validate(raw).model_dump(mode="json", by_alias=True)
    before = original.model_dump_json()
    schema = json_contract.response_schema(prepared.schema, prepared.identifiers)
    assert Draft202012Validator(schema).is_valid(raw)
    decision, changed = prepared.accept(prepared.schema.model_validate(raw))
    restored = Mind.model_validate_json(changed.model_dump_json())
    assert restored == changed and decision.experience_ids
    assert changed.snapshot.experiences[-1].about_id is None
    assert original.model_dump_json() == before
    invalid = deepcopy(raw)
    invalid["experiences"][0]["about_id"] = "@player"
    assert not Draft202012Validator(schema).is_valid(invalid)
    with pytest.raises(ValidationError):
        prepared.schema.model_validate(invalid)


@pytest.mark.parametrize("profile", ["anthropic", "openai", "mistral", "gemma", "deepseek", "qwen"])
async def test_actual_selected_profiles_keep_the_same_generated_experience_constraints(
    monkeypatch, profile
):
    definitions = integrated_request._definitions
    tools_for = submission_fixture.tools_for
    captured = []

    def with_current_source(*args):
        tools = tools_for(*args)
        observed = source(
            tools.observation.message_id, tools.observation.player_request
        ).model_copy(update={"speaker_id": "@player", "role": "user"})
        tools.mind = record(tools.mind, observed, minute=tools.mind.snapshot.sim_minute)
        return tools

    def recorded(*args):
        offered = definitions(*args)
        captured.append(deepcopy(offered[-1]["function"]["parameters"]))
        return offered

    monkeypatch.setattr(integrated_request, "_definitions", recorded)
    monkeypatch.setattr(submission_fixture, "tools_for", with_current_source)
    _decision, usage, _draft, _scope, _system = await deliberate(
        "auto", [[("submit_decision", proposal())]], profile=profile
    )
    schema = captured[0]
    item = resolved(schema, schema["properties"]["experiences"])["items"]
    valid = experience("need_satisfaction", "autonomy")
    fields = item["properties"]
    valid["citations"][0]["fragment_id"] = fields["citations"]["items"]["properties"][
        "fragment_id"
    ]["enum"][0]
    valid["personal_motive_ids"] = [fields["personal_motive_ids"]["items"]["enum"][0]]
    assert Draft202012Validator(item).is_valid(valid)
    assert not Draft202012Validator(item).is_valid({**valid, "about_id": "@player"})
    assert usage.calls == 1 and usage.proposal_repairs == 0


@pytest.mark.parametrize("channel,dimension", [("affect", "joy"), ("need_satisfaction", "rest")])
def test_legacy_values_still_default_to_an_untargeted_observer_state(channel, dimension):
    old = {"channel": channel, "dimension": dimension, "level": "low"}
    value = ExperienceValue.model_validate(old)
    assert value.about_id is None
    assert ExperienceValue.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("length", [400, 401])
def test_generated_message_plan_keeps_its_existing_hard_limit(length):
    _host, _mind, prepared = prepare()
    raw = prepared.schema.model_validate(response(prepared)).model_dump(mode="json", by_alias=True)
    raw["candidates"]["CONTINUE"]["message_plan"] = "x" * length
    schema = json_contract.response_schema(prepared.schema, prepared.identifiers)
    assert Draft202012Validator(schema).is_valid(raw) is (length == 400)
    if length == 400:
        assert prepared.schema.model_validate(raw).candidates["CONTINUE"].intention == "x" * length
        return
    with pytest.raises(ValidationError):
        prepared.schema.model_validate(raw)
