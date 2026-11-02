"""Keep static type mirrors aligned with the dynamically trimmed LLM schemas."""

import ast
import inspect
import typing

import pytest

from backend.engine import llm_intents, rule_engine


@pytest.mark.parametrize("name", ["MechanicsIntent", "ChatProgressionIntent"])
def test_static_intent_fields_match_runtime_schema(name):
    tree = ast.parse(inspect.getsource(llm_intents))
    branch = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING"
    )
    declaration = next(
        node for node in branch.body if isinstance(node, ast.ClassDef) and node.name == name
    )
    annotations = {
        node.target.id: node.annotation
        for node in declaration.body
        if isinstance(node, ast.AnnAssign)
    }
    runtime = getattr(llm_intents, name)
    assert annotations.keys() == runtime.model_fields.keys()
    namespace = {**vars(typing), **vars(rule_engine), **vars(llm_intents)}
    static_contract = type(
        "StaticContract",
        (),
        {"__annotations__": {key: ast.unparse(value) for key, value in annotations.items()}},
    )
    resolved = typing.get_type_hints(static_contract, globalns=namespace)
    for field, annotation in resolved.items():
        assert annotation == runtime.model_fields[field].annotation, field
