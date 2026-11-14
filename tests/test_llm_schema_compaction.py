"""Schema sharing preserves validation, reference resolution and literal JSON values."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_native_guidance import guidance
from backend.core.llm_request_tuning import compact_json_schema
from backend.core.llm_schema_compaction import safe_to_share, schema_nodes, share_schema


def repeated_schema():
    return {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "minLength": 2,
                "maxLength": 12,
                "pattern": "^[A-Z]+$",
                "description": "A stable bounded code identifying this neutral record.",
            },
            "count": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["code"],
        "additionalProperties": False,
    }


def test_exact_subtree_sharing_preserves_validation_and_existing_definitions():
    repeated = repeated_schema()
    schema = {
        "$defs": {"__shared_0": {"type": "null"}, "a/~": repeated},
        "type": "object",
        "properties": {
            "": repeated,
            "a/~": repeated,
            "by_ref": {"$ref": "#/$defs/a~1~0"},
            "values": {"type": "array", "items": repeated, "minItems": 1, "maxItems": 2},
        },
        "required": ["", "a/~", "by_ref", "values"],
        "additionalProperties": False,
    }
    original = deepcopy(schema)
    compacted = share_schema(schema)
    Draft202012Validator.check_schema(compacted)
    assert len(json.dumps(compacted)) < len(json.dumps(schema))
    assert compacted["$defs"]["__shared_0"] == {"type": "null"}
    assert "__shared_0_" in compacted["$defs"]
    assert schema == original
    witness = {"": {"code": "OK"}, "a/~": {"code": "OK"}, "by_ref": {"code": "OK"}}
    witnesses = [
        {**witness, "values": [{"code": "OK", "count": 1}]},
        {**witness, "values": []},
        {**witness, "values": [{"code": "OK"}] * 3},
        {**witness, "values": [{"code": "x"}]},
        {**witness, "values": [{"code": "OK", "count": 0}]},
        {**witness, "values": [{"code": "OK", "extra": True}]},
        {**witness, "values": [None]},
        {**witness, "values": [{}]},
        {"values": [{"code": "OK"}]},
        {**witness, "values": [{"code": "OK"}], "unknown": 1},
    ]
    before, after = Draft202012Validator(schema), Draft202012Validator(compacted)
    assert before.is_valid(witnesses[0])
    assert all(before.is_valid(value) == after.is_valid(value) for value in witnesses)


@pytest.mark.parametrize("keyword", ["oneOf", "anyOf", "allOf"])
def test_sharing_preserves_combinator_and_nullable_branch_semantics(keyword):
    rule = {keyword: [repeated_schema(), {"type": "null"}]}
    schema = {"type": "array", "prefixItems": [rule, rule], "items": False, "minItems": 2}
    compacted = share_schema(schema)
    before, after = Draft202012Validator(schema), Draft202012Validator(compacted)
    for item in ({"code": "OK"}, {"code": "x"}, None, 3, {}, {"code": "OK", "count": 9}):
        for other in ({"code": "OK"}, None, "unrelated"):
            value = [item, other]
            assert before.is_valid(value) == after.is_valid(value)


@pytest.mark.parametrize(
    "keyword",
    [
        "$id",
        "id",
        "$anchor",
        "$dynamicAnchor",
        "$dynamicRef",
        "$recursiveAnchor",
        "$recursiveRef",
        "unevaluatedProperties",
        "unevaluatedItems",
    ],
)
def test_scope_sensitive_schemas_are_kept_unchanged(keyword):
    repeated = repeated_schema()
    schema = {"properties": {"first": repeated, "second": repeated, "scoped": {keyword: "scope"}}}
    assert not safe_to_share(schema)
    assert share_schema(schema) == schema


@pytest.mark.parametrize(
    "reference",
    [
        "#",
        "#/$defs/missing",
        "#/$defs/Foo/nope",
        "#/$defs/Foo~2",
        "#/$defs/%46oo",
        "other.json",
        None,
        3,
        {},
        [],
    ],
)
def test_unsupported_or_unresolved_references_are_kept_unchanged(reference):
    schema = {"$defs": {"Foo": repeated_schema()}, "properties": {"x": {"$ref": reference}}}
    assert not safe_to_share(schema)
    assert share_schema(schema) == schema


def test_static_reference_cycles_are_kept_unchanged():
    schema = {
        "$defs": {"First": {"$ref": "#/$defs/Second"}, "Second": {"$ref": "#/$defs/First"}},
        "properties": {"x": {"$ref": "#/$defs/First"}},
    }
    assert not safe_to_share(schema)
    assert share_schema(schema) == schema


def test_mutable_container_cycles_bail_without_recursing_forever():
    schema = {"properties": {}}
    schema["properties"]["self"] = schema
    assert not safe_to_share(schema)
    copied = share_schema(schema)
    assert copied is copied["properties"]["self"]
    assert copied is not schema


def test_literal_json_and_schema_property_names_are_opaque_to_both_compactors():
    literal = {
        "title": "Literal title must remain.",
        "$id": "literal identity",
        "$ref": "not a schema reference",
        "type": "object",
        "properties": {"title": {"title": "Nested literal title."}},
    }
    schema = {
        "title": "Schema title may be omitted from the legacy prompt.",
        "type": "object",
        "properties": {
            "title": {"title": "Field title", "const": literal, "default": literal},
            "enum": {"enum": [literal], "examples": [literal]},
            "first": repeated_schema(),
            "second": repeated_schema(),
        },
    }
    compacted = compact_json_schema(schema)
    shared = share_schema(schema)
    assert "title" not in compacted
    assert "title" in compacted["properties"]
    assert compacted["properties"]["title"] == {"const": literal, "default": literal}
    assert compacted["properties"]["enum"] == {"enum": [literal], "examples": [literal]}
    assert shared["properties"]["title"]["const"] == literal
    assert shared["properties"]["enum"]["enum"] == [literal]
    assert safe_to_share(schema)
    assert {path for path, _ in schema_nodes(schema)} == {
        "",
        "/properties/title",
        "/properties/enum",
        "/properties/first",
        "/properties/first/properties/code",
        "/properties/first/properties/count",
        "/properties/second",
        "/properties/second/properties/code",
        "/properties/second/properties/count",
    }


def test_references_into_definition_subpaths_keep_their_original_targets():
    repeated = {
        "type": "object",
        "properties": {
            "x": {"type": "string", "minLength": 3, "maxLength": 20},
            "y": {"type": "integer", "minimum": 1, "maximum": 99},
        },
        "required": ["x"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "$defs": {"Foo": repeated},
        "properties": {"a": {"$ref": "#/$defs/Foo/properties/x"}, "b": repeated},
    }
    witness = {"a": "abc", "b": {"x": "abc"}}
    assert Draft202012Validator(schema).is_valid(witness)
    compacted = share_schema(schema)
    assert compacted == schema
    assert Draft202012Validator(compacted).is_valid(witness)


def test_guidance_retains_nested_rules_once_inside_a_complete_deferred_branch():
    schema = {
        "allOf": [
            {"properties": {"code": {"type": "string", "description": "A unique guidance marker."}}}
        ]
    }
    original = deepcopy(schema)
    text = guidance(schema)
    assert text.count("A unique guidance marker.") == 1
    assert schema == original
