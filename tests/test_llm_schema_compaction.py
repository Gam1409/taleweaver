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


@pytest.mark.parametrize("reserved_name", ["__shared_0", "_s0"])
def test_exact_subtree_sharing_preserves_validation_and_existing_definitions(reserved_name):
    repeated = repeated_schema()
    schema = {
        "$defs": {reserved_name: {"type": "null"}, "a/~": repeated},
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
    assert compacted["$defs"][reserved_name] == {"type": "null"}
    generated = set(compacted["$defs"]) - set(schema["$defs"])
    assert ("_s0_" if reserved_name == "_s0" else "_s0") in generated
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


def test_short_definition_names_preserve_escaped_targets_collisions_and_literal_references():
    target = "#/$defs/Long~1Record~0Name"
    literal = {"$ref": target, "$defs": {"Long/Record~Name": "Literal data"}}
    schema = {
        "$defs": {
            "Long/Record~Name": repeated_schema(),
            "d0": {"type": "integer", "minimum": 1, "maximum": 5},
            "LongOptionalRecord": {"anyOf": [{"$ref": target}, {"type": "null"}]},
        },
        "type": "object",
        "properties": {
            "record": {"$ref": target},
            "optional": {"$ref": "#/$defs/LongOptionalRecord"},
            "count": {"$ref": "#/$defs/d0"},
            "literal": {"const": literal, "default": literal},
        },
        "required": ["record", "optional", "count", "literal"],
        "additionalProperties": False,
    }
    original = deepcopy(schema)
    compacted = share_schema(schema, short_names=True)
    Draft202012Validator.check_schema(compacted)
    assert len(json.dumps(compacted)) < len(json.dumps(schema))
    assert compacted["properties"]["literal"] == {"const": literal, "default": literal}
    assert compacted["$defs"]["d0"] == repeated_schema()
    assert schema == original
    valid = {"record": {"code": "OK"}, "optional": None, "count": 1, "literal": literal}
    witnesses = [
        valid,
        {**valid, "optional": {"code": "VALID", "count": 5}},
        {**valid, "record": {"code": "x"}},
        {**valid, "optional": {"code": "OK", "unknown": True}},
        {**valid, "count": 0},
        {**valid, "literal": {"$ref": "rewritten"}},
        {key: value for key, value in valid.items() if key != "record"},
        {**valid, "unknown": True},
    ]
    before, after = Draft202012Validator(schema), Draft202012Validator(compacted)
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


@pytest.mark.parametrize("short_names", [False, True])
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
def test_scope_sensitive_schemas_are_kept_unchanged(keyword, short_names):
    repeated = repeated_schema()
    schema = {"properties": {"first": repeated, "second": repeated, "scoped": {keyword: "scope"}}}
    assert not safe_to_share(schema)
    assert share_schema(schema, short_names=short_names) == schema


@pytest.mark.parametrize("short_names", [False, True])
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
def test_unsupported_or_unresolved_references_are_kept_unchanged(reference, short_names):
    schema = {"$defs": {"Foo": repeated_schema()}, "properties": {"x": {"$ref": reference}}}
    assert not safe_to_share(schema)
    assert share_schema(schema, short_names=short_names) == schema


@pytest.mark.parametrize("short_names", [False, True])
def test_static_reference_cycles_are_kept_unchanged(short_names):
    schema = {
        "$defs": {"First": {"$ref": "#/$defs/Second"}, "Second": {"$ref": "#/$defs/First"}},
        "properties": {"x": {"$ref": "#/$defs/First"}},
    }
    assert not safe_to_share(schema)
    assert share_schema(schema, short_names=short_names) == schema


@pytest.mark.parametrize("short_names", [False, True])
def test_mutable_container_cycles_bail_without_recursing_forever(short_names):
    schema = {"properties": {}}
    schema["properties"]["self"] = schema
    assert not safe_to_share(schema)
    copied = share_schema(schema, short_names=short_names)
    assert copied is copied["properties"]["self"]
    assert copied is not schema


@pytest.mark.parametrize("short_names", [False, True])
def test_literal_json_and_schema_property_names_are_opaque_to_both_compactors(short_names):
    literal = {
        "title": "Literal title must remain.",
        "$id": "literal identity",
        "$ref": "not a schema reference",
        "type": "object",
        "_s0": {"__shared_0": "Literal keys must not be renamed."},
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
    shared = share_schema(schema, short_names=short_names)
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


@pytest.mark.parametrize("short_names", [False, True])
def test_references_into_definition_subpaths_keep_their_original_targets(short_names):
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
    compacted = share_schema(schema, short_names=short_names)
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
