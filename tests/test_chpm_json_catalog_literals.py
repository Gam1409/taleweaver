"""Portable catalogs preserve literal JSON while removing schema annotations."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm.json_tool_port import compose


@pytest.mark.parametrize(
    "literal",
    [
        {"title": "A literal heading", "default": None},
        {"default": {"title": [None, True, "自由"]}, "$ref": "literal, not a schema ref"},
        {"properties": {"title": {"default": False}}, "enum": [{"title": "data"}]},
    ],
)
def test_compacted_catalog_retains_const_enum_values_and_annotation_named_properties(literal):
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "title": "Schema annotation", "default": "Example"},
            "default": {"const": literal, "title": "Schema annotation"},
            "choice": {"enum": [literal, {}], "default": literal},
        },
        "required": ["title", "default", "choice"],
    }
    tools = [
        {
            "type": "function",
            "function": {"name": "inspect_entity", "parameters": parameters},
        }
    ]
    original = deepcopy(tools)
    _, content = compose([{"role": "user", "content": "{}"}], tools)
    payload = json.loads(content)
    compact = {**payload, **payload["functions"][0]["parameters"]}
    Draft202012Validator.check_schema(compact)
    canonical = Draft202012Validator(parameters)
    catalog = Draft202012Validator(compact)
    valid = {"title": "A title", "default": literal, "choice": literal}

    assert canonical.is_valid(valid) and catalog.is_valid(valid)
    assert catalog.is_valid({**valid, "choice": {}})
    assert not catalog.is_valid({**valid, "default": None})
    assert not catalog.is_valid({**valid, "title": False})
    assert "Schema annotation" not in content
    assert tools == original
