"""Native decoding keeps canonical guidance without duplicating the complete grammar."""

import json
from copy import deepcopy

import pytest
from pydantic import BaseModel, ConfigDict, Field

from backend.core.llm_native_guidance import guidance
from backend.core.llm_provider_config import JSON_SCHEMA_INSTRUCTION
from backend.core.llm_request_tuning import compact_json_schema
from backend.core.llm_schema_compaction import schema_nodes
from tests.test_llm_structured_single_attempt import router


def notes(text):
    return json.loads(text.split("\n", 3)[-1])


def test_root_and_escaped_schema_pointers_retain_exact_annotation_values():
    schema = {
        "description": "Root guidance.",
        "default": {"title": "Literal title", "$ref": "inert data"},
        "examples": [{"": "example", "a/~": "明日"}],
        "discriminator": {"propertyName": "kind"},
        "properties": {
            "": {"description": "Empty member guidance."},
            "a/~": {"description": "Escaped member guidance.", "pattern": "^[A-Z]+$"},
        },
    }
    original = deepcopy(schema)
    result = notes(guidance(schema))
    assert result[""] == {key: schema[key] for key in schema if key != "properties"}
    assert result["/properties/"] == {"description": "Empty member guidance."}
    assert result["/properties/a~1~0"] == schema["properties"]["a/~"]
    assert schema == original


def test_all_deferred_rules_survive_even_when_projection_does_not_report_them():
    schema = {
        "properties": {
            "blank": {"type": "string", "pattern": r"^\s*$"},
            "set": {"type": "array", "uniqueItems": True},
            "map": {"type": "object", "minProperties": 1, "maxProperties": 3},
            "tuple": {"prefixItems": [{"const": 1}, {"const": 2}]},
            "union": {"oneOf": [{"type": "integer"}, {"type": "number"}]},
            "combined": {"allOf": [{"maximum": 4}, {"minimum": 1}]},
        }
    }
    result = notes(guidance(schema))
    for name, value in schema["properties"].items():
        assert result[f"/properties/{name}"] == {
            key: item for key, item in value.items() if key != "type"
        }


@pytest.mark.parametrize(
    "schema,local_checks",
    [
        ({"type": "string", "unknownConstraint": {"minimum": 1}}, ()),
        ({"type": "string", "description": "Keep this."}, ("future_local_rule",)),
        ({"$id": "https://offline.invalid/schema", "description": "Keep scope."}, ()),
        ({"$defs": {"A": {"$ref": "#/$defs/A"}}, "description": "Keep recursion."}, ()),
    ],
)
def test_unrecognized_or_scoped_contracts_keep_the_full_canonical_prompt(schema, local_checks):
    assert guidance(schema, local_checks) == JSON_SCHEMA_INSTRUCTION.format(
        schema_json=json.dumps(compact_json_schema(schema), separators=(",", ":"))
    )


class GuidedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(description="Copy the observed code.", pattern="^[A-Z]+$")
    optional_note: str | None = Field(default=None, examples=["A neutral note."])


@pytest.mark.parametrize("mode", ["prompt", "json_object"])
def test_legacy_modes_keep_the_complete_canonical_schema_and_original_context(monkeypatch, mode):
    llm = router(monkeypatch, mode)
    system, payload = "Original domain instructions.", '{"source":"明日"}'
    built = llm._build_structured_request(system, payload, GuidedReply, "local-model")
    assert built.system_prompt == system + JSON_SCHEMA_INSTRUCTION.format(
        schema_json=json.dumps(
            compact_json_schema(GuidedReply.model_json_schema()), separators=(",", ":")
        )
    )
    assert built.kwargs["messages"][1]["content"] == payload
    assert built.kwargs.get("response_format") == (
        {"type": "json_object"} if mode == "json_object" else None
    )


def test_native_mode_keeps_field_guidance_and_defers_text_validation_without_full_schema(
    monkeypatch,
):
    llm = router(monkeypatch, "json_schema")
    system, payload = "Original domain instructions.", '{"source":"ABC"}'
    built = llm._build_structured_request(system, payload, GuidedReply, "local-model")
    assert built.system_prompt.startswith(system)
    assert "SCHEMA:" not in built.system_prompt
    result = notes(built.system_prompt[len(system) :])
    assert result["/properties/code"] == {
        "description": "Copy the observed code.",
        "pattern": "^[A-Z]+$",
    }
    assert result["/properties/optional_note"] == {"default": None, "examples": ["A neutral note."]}
    assert built.kwargs["messages"][1]["content"] == payload
    native = built.kwargs["response_format"]["json_schema"]["schema"]
    assert "pattern" not in native["properties"]["code"]
    assert native["properties"]["code"]["type"] == "string"


def test_native_fallback_retains_full_schema_guidance(monkeypatch):
    llm = router(monkeypatch, "json_schema")
    # An open-ended heterogeneous prefix cannot be represented by the decoder projection.
    schema = {
        "type": "object",
        "properties": {"tuple_value": {"type": "array", "prefixItems": [{"type": "integer"}]}},
    }
    built = llm._build_structured_request(
        "Original domain.", "payload", GuidedReply, "local-model", response_schema=schema
    )
    assert built.kwargs["response_format"] == {"type": "json_object"}
    assert "SCHEMA:" in built.system_prompt
    assert json.loads(built.system_prompt.rsplit("SCHEMA:\n", 1)[1]) == schema


def reconciliation_fixture(*, staging=False, passages=18):
    from backend.engine.narrated_items import coverage, independent_state, reference_schema
    from backend.engine.narrated_items.schema import (
        INSTRUCTIONS,
        ItemExtraction,
        SharedItemExtraction,
    )
    from backend.engine.narrated_items.source_catalog import Catalog
    from backend.engine.narrated_movement.schema import INSTRUCTIONS as MOVEMENT
    from backend.engine.physical_conditions.prompts import INSTRUCTIONS as CONDITIONS
    from backend.engine.scene_continuity.prompts import INSTRUCTIONS as CONTINUITY
    from backend.engine.scene_staging.schema import SHARED_INSTRUCTIONS

    narration = "\n\n".join(
        f"Mira places numbered marker {index} on the workbench." for index in range(passages)
    )
    catalog = Catalog(narration, "A quiet workshop.", scope="neutral-reconciliation")
    assert len(catalog.narration_passages) == passages
    schema = reference_schema.build(
        SharedItemExtraction if staging else ItemExtraction, catalog, complete=True
    )
    instructions = (
        INSTRUCTIONS
        + CONDITIONS
        + CONTINUITY
        + MOVEMENT
        + independent_state.INSTRUCTIONS
        + (SHARED_INSTRUCTIONS if staging else "")
    )
    payload = json.dumps(
        {
            "completed_narration": catalog.narration_passages,
            "extraction_coverage_groups": coverage.groups(catalog),
            "player_actor_id": "__player__",
            "actors": [{"id": "mira", "name": "Mira"}, {"id": "noor", "name": "Noor"}],
            "items": [],
            "physical_conditions": [],
            "scene_staging": {} if staging else None,
        },
        ensure_ascii=False,
    )
    return instructions, payload, schema, SharedItemExtraction


def input_size(kwargs):
    return len(
        json.dumps(
            {key: kwargs[key] for key in ("messages", "response_format") if key in kwargs},
            ensure_ascii=False,
        )
    )


def test_real_reconciliation_schema_fits_existing_budget_without_removing_source_data(monkeypatch):
    from backend.core.llm_schema_projection import project

    instructions, payload, schema, model = reconciliation_fixture()
    llm = router(monkeypatch, "json_schema")
    built = llm._build_structured_request(
        instructions, payload, model, "local-model", response_schema=schema
    )
    old_wire = {
        "messages": [
            {
                "role": "system",
                "content": instructions
                + JSON_SCHEMA_INSTRUCTION.format(
                    schema_json=json.dumps(compact_json_schema(schema), separators=(",", ":"))
                ),
            },
            {"role": "user", "content": payload},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": model.__name__, "schema": project(schema).schema},
        },
    }
    assert input_size(old_wire) > 64000
    assert input_size(built.kwargs) <= 64000
    assert built.kwargs["messages"][1]["content"] == payload
    assert built.system_prompt.startswith(instructions)
    result = notes(built.system_prompt[len(instructions) :])
    # Rules nested in preserved complete branches are carried by those branches verbatim.
    for path, node in schema_nodes(schema):
        for key in (
            "description",
            "default",
            "examples",
            "discriminator",
            "pattern",
            "uniqueItems",
            "minProperties",
            "maxProperties",
            "oneOf",
            "allOf",
            "prefixItems",
        ):
            if key not in node:
                continue
            if path in result and key in result[path]:
                assert result[path][key] == node[key]
                continue
            assert any(
                path.startswith(parent + "/" + keyword + "/")
                for parent, entry in result.items()
                for keyword in ("oneOf", "allOf", "prefixItems")
                if keyword in entry
            )


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
def test_larger_optional_staging_context_keeps_data_and_respects_prepared_admission(
    monkeypatch, mode
):
    from backend.core.llm_structured_execution import require_input_budget

    instructions, payload, schema, model = reconciliation_fixture(staging=True, passages=36)
    built = router(monkeypatch, mode)._build_structured_request(
        instructions, payload, model, "local-model", response_schema=schema
    )
    assert built.kwargs["messages"][1]["content"] == payload
    assert built.system_prompt.startswith(instructions)
    assert input_size(built.kwargs) > 64000
    with pytest.raises(ValueError, match="input"):
        require_input_budget(built.kwargs, 64000)
