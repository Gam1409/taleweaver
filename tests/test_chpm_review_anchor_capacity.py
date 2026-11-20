"""Reviewer wire limits agree with the host's existing per-actor anchor capacity."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm import agenda, expression, inference, json_contract, passages
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.passages import Review
from backend.engine.chpm.schema import AgendaIntent, Projection, Verdict
from tests.test_chpm_json_schema_references import resolved

FIELDS = ("evidence", "actions", "agenda_evidence")
AVAILABLE = {
    "p0": 'Lina: "I will inspect the label."',
    "p1": "Lina folds the route map.",
    "p2": 'Lina: "I will verify the cabinet."',
    "p3": 'Mira: "I will inspect the seal."',
    "p4": "Mira picks up a pencil.",
}


def identifiers(actors):
    return {"actor_id": actors, "speaker_id": ["lina", "mira"], "passage_id": list(AVAILABLE)}


def decoder(actors):
    router = SimpleNamespace(
        provider="custom_openai", model="offline", custom_response_format="json_schema"
    )
    result = inference.transport_options(router, Review, identifiers(actors))
    return result["response_format"]["json_schema"]["schema"]


def decisions(actors, *, with_agenda=False):
    return {
        actor: SimpleNamespace(
            selected=SimpleNamespace(
                kind="CONTINUE",
                agenda_change=AgendaIntent(action="goal", text="Inspect the workshop equipment.")
                if with_agenda
                else None,
            )
        )
        for actor in actors
    }


@pytest.mark.parametrize("field", FIELDS)
def test_single_actor_duplicates_previously_schema_valid_are_rejected_by_decoder(field):
    body = {"matches": True, "evidence": [{"actor_id": "lina", "passage_id": "p0"}]}
    body[field] = [
        {"actor_id": "lina", "passage_id": "p0"},
        {"actor_id": "lina", "passage_id": "p2"},
    ]
    assert Draft202012Validator(Review.model_json_schema()).is_valid(body)
    verdict = passages.resolve(Review.model_validate(body), AVAILABLE)
    with pytest.raises(ChpmError):
        if field == "agenda_evidence":
            agenda.validate_evidence(decisions(["lina"], with_agenda=True), verdict)
        else:
            expression.validate(decisions(["lina"]), verdict, "\n".join(AVAILABLE.values()))
    schema = decoder(["lina"])
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(body))
    assert any(error.validator == "maxItems" and list(error.path) == [field] for error in errors)


def test_two_actors_can_each_have_speech_action_and_agenda_anchors():
    actors = ["lina", "mira"]
    body = {
        "matches": True,
        "evidence": [
            {"actor_id": "lina", "passage_id": "p0"},
            {"actor_id": "mira", "passage_id": "p3"},
        ],
        "actions": [
            {"actor_id": "lina", "passage_id": "p1"},
            {"actor_id": "mira", "passage_id": "p4"},
        ],
        "agenda_evidence": [
            {"actor_id": "lina", "passage_id": "p0"},
            {"actor_id": "mira", "passage_id": "p3"},
        ],
    }
    assert Draft202012Validator(decoder(actors)).is_valid(body)
    verdict = passages.resolve(Review.model_validate(body), AVAILABLE)
    expression.validate(decisions(actors, with_agenda=True), verdict, "\n".join(AVAILABLE.values()))
    agenda.validate_evidence(decisions(actors, with_agenda=True), verdict)


def test_multi_actor_capacity_does_not_replace_the_host_uniqueness_guard():
    body = {
        "matches": True,
        "evidence": [
            {"actor_id": "lina", "passage_id": "p0"},
            {"actor_id": "lina", "passage_id": "p2"},
        ],
    }
    assert Draft202012Validator(decoder(["lina", "mira"])).is_valid(body)
    verdict = passages.resolve(Review.model_validate(body), AVAILABLE)
    with pytest.raises(ChpmError, match="exactly once"):
        expression.validate(decisions(["lina", "mira"]), verdict, "\n".join(AVAILABLE.values()))


@pytest.mark.parametrize(
    ("actors", "capacity"), [([], 0), (["lina"], 1), (["lina", "mira"], 2), (["lina", "lina"], 1)]
)
def test_anchor_capacities_follow_the_distinct_controlled_cast(actors, capacity):
    schema = json_contract.response_schema(Review, identifiers(actors))
    assert all(schema["properties"][field]["maxItems"] == capacity for field in FIELDS)
    if not actors:
        assert Draft202012Validator(schema).is_valid({"matches": True})
    else:
        assert schema["properties"]["heard"]["maxItems"] == 12


@pytest.mark.parametrize("known", [None, {}, {"passage_id": ["p0"]}])
def test_absent_actor_allowlist_keeps_existing_global_array_limits(known):
    schema = json_contract.response_schema(Review, known)
    assert all(schema["properties"][field]["maxItems"] == 20 for field in FIELDS)
    assert schema["properties"]["heard"]["maxItems"] == 12


def test_cast_specific_caps_do_not_mutate_inputs_or_other_model_schemas():
    original = deepcopy(Review.model_json_schema())
    known = identifiers(["lina"])
    before = deepcopy(known)
    first = json_contract.response_schema(Review, known)
    second = json_contract.response_schema(Review, identifiers(["lina", "mira"]))
    assert first["properties"]["evidence"]["maxItems"] == 1
    assert second["properties"]["evidence"]["maxItems"] == 2
    assert known == before and Review.model_json_schema() == original
    assert json_contract.response_schema(Verdict, known)["properties"]["evidence"]["maxItems"] == 20
    assert (
        json_contract.response_schema(Projection, known)["properties"]["audience"]["maxItems"] == 20
    )


def test_prompt_schema_and_native_decoder_receive_the_same_anchor_capacity():
    system, _ = inference.compose("Review all passages.", {}, Review, identifiers(["lina"]))
    prompted = json.loads(system.split("JSON schema:\n", 1)[1])
    native = decoder(["lina"])
    for field in FIELDS:
        assert resolved(prompted, prompted["properties"][field])["maxItems"] == 1
        body = {"matches": True, field: [{"actor_id": "lina", "passage_id": "p0"}]}
        for contract in (prompted, native):
            validator = Draft202012Validator(contract)
            assert validator.is_valid(body)
            repeated = {**body, field: [*body[field], *body[field]]}
            errors = list(validator.iter_errors(repeated))
            assert any(
                error.validator == "maxItems" and list(error.path) == [field] for error in errors
            )
    assert native["properties"]["heard"]["maxItems"] == 12
