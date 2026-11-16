"""The advertised garment shape must agree with validation and safe owner diagnostics."""

import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from backend.api.routes.adventures.state_checks import state_checks
from backend.engine.narrated_items.diagnostics import describe_failure
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemExtraction
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import action
from tests.test_vn_turn_integration import seed_vn


def new_action(**changes):
    item = {
        "kind": "clothing",
        "name": "Scarf",
        "description": "A plain wool scarf.",
        "clothing": {"layer": 2, "coverage": ["torso"]},
        "wearable_slots": ["Neck"],
        **changes,
    }
    return {**action().model_dump(), "item_id": None, "new_item": item}


def test_wire_schema_requires_garment_metadata_and_nonempty_slots_for_clothing():
    schema = ItemExtraction.model_json_schema()
    item = schema["$defs"]["NewItemAction"]["properties"]["new_item"]
    assert item["discriminator"]["propertyName"] == "kind"
    clothing = schema["$defs"]["NewClothingItem"]
    assert {"clothing", "wearable_slots"} <= set(clothing["required"])
    assert clothing["properties"]["wearable_slots"]["minItems"] == 1
    assert "$ref" in clothing["properties"]["clothing"]
    ordinary = schema["$defs"]["NewOrdinaryItem"]
    assert ordinary["properties"]["clothing"]["type"] == "null"
    assert ordinary["properties"]["wearable_slots"]["maxItems"] == 0


@pytest.mark.parametrize(
    "changes,valid",
    [
        ({}, True),
        ({"clothing": None}, False),
        ({"wearable_slots": []}, False),
        ({"wearable_slots": ["Neck"] * 4}, True),
        ({"wearable_slots": ["Neck"] * 5}, False),
        ({"kind": "ordinary"}, False),
        ({"kind": "ordinary", "clothing": None, "wearable_slots": []}, True),
    ],
)
def test_wire_and_host_agree_on_new_item_metadata_and_slot_boundaries(changes, valid):
    payload = {"actions": [new_action(**changes)]}
    validator = Draft202012Validator(ItemExtraction.model_json_schema())
    assert validator.is_valid(payload) is valid
    if valid:
        assert ItemExtraction.model_validate(payload).actions
        return
    with pytest.raises(ValidationError):
        ItemExtraction.model_validate(payload)


@pytest.mark.parametrize("count", [1, 6, 7])
def test_new_item_branches_preserve_the_shared_action_limit(count):
    payload = {"actions": [new_action()] * count}
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(payload) is (
        count <= 6
    )
    if count <= 6:
        value = ItemExtraction.model_validate(payload)
        assert len(value.actions) == count
        assert ItemExtraction.model_validate_json(value.model_dump_json()) == value
        return
    with pytest.raises(ValidationError):
        ItemExtraction.model_validate(payload)


@pytest.mark.parametrize("kind", ["ordinary", "clothing"])
def test_existing_valid_items_keep_their_shape_and_round_trip(kind):
    proposal = new_action()
    if kind == "ordinary":
        proposal["new_item"].update(kind=kind, clothing=None, wearable_slots=[])
    value = ItemExtraction.model_validate({"actions": [proposal]})
    assert ItemExtraction.model_validate_json(value.model_dump_json()) == value
    assert value.actions[0].new_item.model_dump() == {
        **proposal["new_item"],
        **(
            {"clothing": value.actions[0].new_item.clothing.model_dump()}
            if kind == "clothing"
            else {}
        ),
    }


def test_schema_failure_identifies_the_second_action_and_safe_constraint_without_model_text():
    invalid = new_action(wearable_slots=[])
    with pytest.raises(ValidationError) as error:
        ItemExtraction.model_validate({"actions": [action().model_dump(), invalid]})
    wrapped = ValueError("SECRET_PROVIDER_KEY")
    wrapped.__cause__ = error.value
    failure = describe_failure(wrapped)
    details = failure.payload()["validation_details"]
    assert any(row["field"] == "actions.1.new_item.wearable_slots" for row in details)
    assert any("at least 1" in row["reason"] for row in details)
    assert "actions.1" in failure.message()
    assert "SECRET_PROVIDER_KEY" not in json.dumps(failure.payload())


def test_unknown_custom_validation_errors_do_not_expose_their_code_message_or_input():
    error = ValidationError.from_exception_data(
        "ItemExtraction",
        [
            {
                "type": PydanticCustomError("SECRET_CODE", "SECRET_MESSAGE"),
                "loc": ("actions", 1, "new_item", "SECRET_FIELD"),
                "input": "SECRET_INPUT",
            }
        ],
    )
    failure = describe_failure(error)
    assert "SECRET" not in json.dumps(failure.payload())
    assert failure.validation_details[0]["field"] == "actions.1.new_item"


@pytest.mark.parametrize("legacy", [False, True])
async def test_saved_schema_diagnostics_are_visible_to_owner_without_changing_the_check(legacy):
    failure = {
        "code": "invalid_schema",
        "reason": "Invalid garment data.",
        "validation_fields": ["actions.1.new_item"],
    }
    if not legacy:
        failure["validation_details"] = [
            {
                "field": "actions.1.new_item.wearable_slots",
                "code": "too_short",
                "reason": "List should have at least 1 item.",
            }
        ]
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {**state.entity_states, KEY: {"status": "failed", "failure": failure}}
        await db.commit()
        await db.refresh(state)
        report = await state_checks("session-1", db, user)
        assert report["items"]["failure"] == failure
        assert state.entity_states[KEY]["failure"] == failure
