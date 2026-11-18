"""A current rejection reaches repair without importing unused expression effects."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.core.llm_completion_capture import record_completion
from backend.engine.chpm import inference, json_contract, passages
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.chpm.state import KEY, load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_json_contract import host
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_action_execution_policy import ExecutionRoles

IDS = {"review_scope": ["scope"], "actor_id": ["npc"], "passage_id": ["p0"]}
EFFECTS = ("evidence", "actions", "heard", "causal_updates")


def rejection():
    return {
        "review_scope": "scope",
        "matches": False,
        "rejections": [{"reason_code": "world", "actor_id": "npc", "passage_id": "p0"}],
        "evidence": {"npc": [{"actor_id": "foreign", "passage_id": "old"}]},
        "actions": {"npc": [{"actor_id": "foreign", "passage_id": "old"}]},
        "heard": {"actor_id": "foreign", "speaker_id": "secret", "origin_id": "old"},
        "causal_updates": [{"actor_id": "foreign", "action": "open", "facts": "untrusted"}],
    }


async def request(body, *, identifiers=None):
    manager, usage = host(json.dumps(body)), Usage()
    review = await inference.request(
        manager,
        Settings(),
        usage,
        "Review the supplied outcome.",
        {},
        passages.SharedReview,
        "validation",
        identifiers=IDS if identifiers is None else identifiers,
    )
    return review, manager, usage


async def test_current_rejection_survives_unused_invalid_effects_in_production_request():
    body = rejection()
    before = deepcopy(body)
    review, manager, usage = await request(body)
    passages.validate_shared(review, "scope", {"p0": "The clerk moves the parcel."}, {"npc"})
    assert review.matches is False
    assert review.rejections[0].reason_code == "world"
    assert all(getattr(review, field) == [] for field in EFFECTS)
    assert usage.calls == 1 and usage.proposal_repairs == 0
    assert usage.output_chars == len(json.dumps(body))
    manager._chpm_model_factory("small").aexecute_simple_task.assert_awaited_once()
    assert body == before


def test_negative_provider_dto_cannot_retain_well_formed_untrusted_effects():
    body = rejection()
    body["evidence"] = [{"actor_id": "foreign", "passage_id": "old"}]
    body["actions"] = [{"actor_id": "foreign", "passage_id": "old"}]
    body["heard"] = [{"actor_id": "foreign", "speaker_id": "secret", "passage_id": "old"}]
    before = deepcopy(body)
    review = passages.SharedReview.model_validate(body)
    assert review.matches is False
    assert all(getattr(review, field) == [] for field in EFFECTS)
    assert body == before
    assert passages.SharedReview.model_validate_json(review.model_dump_json()) == review


async def test_legacy_negative_review_with_empty_reasons_still_has_no_effects():
    body = {
        "review_scope": "scope",
        "matches": False,
        "rejections": [],
        "evidence": [{"actor_id": "npc", "passage_id": "p0"}],
        "actions": [{"actor_id": "npc", "passage_id": "p0"}],
    }
    review, _manager, usage = await request(body)
    assert review.matches is False and review.rejections == []
    assert all(getattr(review, field) == [] for field in EFFECTS)
    assert usage.calls == 1


async def test_empty_reasons_do_not_rescue_malformed_positive_fields():
    body = {**rejection(), "rejections": []}
    with pytest.raises(inference.InvalidResponseError):
        await request(body)
    with pytest.raises(ValidationError):
        passages.SharedReview.model_validate(body)


async def test_raw_output_cutoff_is_checked_before_rejected_fields_are_discarded():
    body = rejection()
    body["evidence"] = "untrusted " * 1000
    serialized = json.dumps(body)
    manager, usage = host(""), Usage()

    async def truncated(*_args, **_kwargs):
        record_completion(
            {"choices": [{"finish_reason": "length"}], "usage": {"completion_tokens": 4096}}
        )
        return serialized

    manager._chpm_model_factory("small").aexecute_simple_task.side_effect = truncated
    with pytest.raises(inference.OutputBudgetError):
        await inference.request(
            manager,
            Settings(),
            usage,
            "Review the supplied outcome.",
            {},
            passages.SharedReview,
            "validation",
            identifiers=IDS,
        )
    assert usage.output_chars == len(serialized)
    assert usage.calls == 1 and usage.format_repairs == 0


@pytest.mark.parametrize("field", EFFECTS)
@pytest.mark.parametrize("value", [None, "invalid", 7, {"foreign": [None]}])
async def test_unused_rejected_effect_shapes_never_gain_authority(field, value):
    body = rejection()
    body[field] = value
    review, _manager, usage = await request(body)
    assert review.matches is False and all(getattr(review, key) == [] for key in EFFECTS)
    assert usage.calls == 1


@pytest.mark.parametrize(
    "change",
    [
        {"review_scope": "old-scope"},
        {"review_scope": " scope "},
        {"rejections": [{"reason_code": "unknown", "actor_id": "npc", "passage_id": "p0"}]},
        {"rejections": [{"reason_code": "world", "actor_id": "foreign", "passage_id": "p0"}]},
        {"rejections": [{"reason_code": "world", "actor_id": " npc ", "passage_id": "p0"}]},
        {"rejections": [{"reason_code": "world", "actor_id": "npc", "passage_id": "old"}]},
        {"rejections": [{"reason_code": "world", "actor_id": "npc", "passage_id": " p0 "}]},
        {"rejections": [{"reason_code": "world"}] * 9},
        {"rejections": {"npc": [{"reason_code": "world"}]}},
        {"rejections": [{"reason_code": "world", "effect": {"item_id": "PARCEL"}}]},
        {"unexpected_effect": {"item_id": "PARCEL"}},
    ],
)
async def test_rejection_scope_references_and_contract_remain_strict(change):
    body = {**rejection(), **change}
    with pytest.raises(inference.InvalidResponseError):
        await request(body)


@pytest.mark.parametrize("matches", [True, "false", 0, None])
async def test_only_literal_false_qualifies_for_rejected_effect_projection(matches):
    body = {**rejection(), "matches": matches}
    with pytest.raises(inference.InvalidResponseError):
        await request(body)
    with pytest.raises(ValidationError):
        passages.SharedReview.model_validate(body)


async def test_a_positive_review_retains_and_validates_its_effects():
    body = {
        "review_scope": "scope",
        "matches": True,
        "evidence": [{"actor_id": "npc", "passage_id": "p0"}],
        "actions": [{"actor_id": "npc", "passage_id": "p0"}],
    }
    review, _manager, usage = await request(body)
    assert review.matches is True
    assert review.evidence[0].passage_id == review.actions[0].passage_id == "p0"
    assert usage.calls == 1
    body["evidence"][0]["actor_id"] = "foreign"
    with pytest.raises(inference.InvalidResponseError):
        await request(body)


def test_provided_review_schema_keeps_the_existing_bounds_and_reference_enums():
    schema = json_contract.response_schema(passages.SharedReview, IDS, explicit_keys=True)
    assert schema["properties"]["review_scope"]["enum"] == ["scope"]
    assert schema["properties"]["matches"] == {"type": "boolean"}
    assert schema["properties"]["rejections"]["maxItems"] == 8
    for field in ("evidence", "actions"):
        assert schema["properties"][field]["type"] == "array"
        assert schema["properties"][field]["maxItems"] == 1
    rejection_schema = schema["$defs"]["ReviewRejection"]
    assert rejection_schema["additionalProperties"] is False
    assert rejection_schema["properties"]["actor_id"]["enum"] == ["npc", None]
    assert rejection_schema["properties"]["passage_id"]["enum"] == ["p0", None]


class RejectedEffectsRoles(ExecutionRoles):
    def __init__(self):
        super().__init__(repair=True)

    async def simple(self, system, payload, model, **kwargs):
        result = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") == "validation" and len(self.reviews) == 1:
            body = json.loads(result)
            body.update({field: rejection()[field] for field in EFFECTS})
            return json.dumps(body)
        return result


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_negative_wire_uses_existing_single_repair_through_real_turn(monkeypatch, protocol):
    roles = RejectedEffectsRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events)
        assert len(roles.repairs) == 1 and len(roles.reviews) == 2
        assert load(manager.state).usage.calls == 6
        assert load(manager.state).usage.proposal_repairs == 0
        for _system, body in roles.reviews:
            assert [
                row["status"] for row in body["contract"]["LINA"]["authoritative_command_outcomes"]
            ] == [
                "applied",
                "applied",
            ]
