"""Player item identity rules reach the structured decoder, not only host validation."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.core.llm_schema_projection import project
from backend.core.llm_structured_output import select
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.visual_novel.intent import progression_schema
from backend.engine.visual_novel.player_item_contracts import PlayerItemAction

EXISTING = ("take", "give", "drop", "consume", "destroy", "wear", "remove", "adjust")


def action(operation="take", **fields):
    return {
        "performer_id": "__player__",
        "operation": operation,
        "passage_id": "player:p0",
        "basis": "performed",
        **fields,
    }


def validators():
    schema = PlayerItemAction.model_json_schema()
    return (Draft202012Validator(schema), Draft202012Validator(project(schema).schema))


@pytest.mark.parametrize("operation", EXISTING)
@pytest.mark.parametrize("fields", [{}, {"item_id": None}])
def test_missing_existing_item_identity_is_rejected_by_both_advertised_decoders(operation, fields):
    raw = action(operation, **fields)
    with pytest.raises(ValidationError):
        PlayerItemAction.model_validate(raw)
    assert all(not decoder.is_valid(raw) for decoder in validators())


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"creation_ref": None},
        {"creation_ref": True},
        {"creation_ref": -1},
        {"creation_ref": 3},
        {"creation_ref": 0, "item_id": "EXISTING"},
    ],
)
def test_creation_identity_is_an_explicit_bounded_reference_and_never_an_existing_id(fields):
    raw = action("acquire_garment", **fields)
    with pytest.raises(ValidationError):
        PlayerItemAction.model_validate(raw)
    assert all(not decoder.is_valid(raw) for decoder in validators())


@pytest.mark.parametrize("operation", EXISTING)
def test_existing_identity_still_accepts_legacy_optional_null_creation_reference(operation):
    raw = action(operation, item_id="ORIGINAL", creation_ref=None)
    assert PlayerItemAction.model_validate(raw).item_id == "ORIGINAL"
    assert all(decoder.is_valid(raw) for decoder in validators())


@pytest.mark.parametrize("fields", [{"creation_ref": 0}, {"creation_ref": 2, "item_id": None}])
def test_existing_creation_contract_keeps_optional_null_inactive_item_id(fields):
    raw = action("acquire_garment", **fields)
    assert PlayerItemAction.model_validate(raw).creation_ref == fields["creation_ref"]
    assert all(decoder.is_valid(raw) for decoder in validators())


def test_real_progression_output_schema_requires_identity_and_keeps_observation_actions_empty():
    settings = Settings(
        mode="live", workflow="integrated", action_tools=True, agent_steps=1, actor_ids=["LINA"]
    )
    state = SimpleNamespace(entity_states={KEY: KernelState(settings=settings).model_dump()})
    model = progression_schema(state)
    canonical = model.model_json_schema()
    original = deepcopy(canonical)
    output = select("custom_openai", "local-model", model, custom_mode="json_schema")
    assert output.mode == "json_schema"
    wire = output.response_format["json_schema"]["schema"]
    for schema in (canonical, wire):
        decoder = Draft202012Validator(schema)
        assert not decoder.is_valid({"player_item_actions": [action()]})
        assert decoder.is_valid({"player_item_actions": []})
        assert decoder.is_valid({"player_item_actions": [action(item_id="ORIGINAL")]})
    assert canonical == original
    state.entity_states[KEY]["settings"]["mode"] = "off"
    assert "player_item_actions" not in progression_schema(state).model_fields
