"""Scaled limits prove rejection before amplification, without stress allocations."""

import pytest

from backend.engine.scripting import sandbox


@pytest.fixture
def small_limits(monkeypatch):
    monkeypatch.setattr(sandbox, "MAX_SEQUENCE_LENGTH", 100)
    monkeypatch.setattr(sandbox.logger, "info", lambda *_args, **_kwargs: None)
    observed = []
    check = sandbox._check_sequence_size

    def record(value):
        if isinstance(value, (str, bytes, list, tuple, dict)):
            observed.append(len(value))
        return check(value)

    monkeypatch.setattr(sandbox, "_check_sequence_size", record)
    return observed


@pytest.mark.parametrize(
    "expression",
    [
        "('x' * 100).replace('x', 'y' * 100)",
        "str.replace('x' * 100, 'x', 'y' * 100)",
        "(b'x' * 100).replace(b'x', b'y' * 100)",
        "('x' * 100).join(['a'] * 100)",
        "str.join('x' * 100, ['a'] * 100)",
        "'%10000s' % 'x'",
        "b'%10000s' % b'x'",
        "'%*s' % (10000, 'x')",
        "'%.*f' % (10000, 1.0)",
        "'%(item)10000s' % {'item': 'x'}",
        "str(['x' * 50] * 50)",
        "f'{items}'",
        "print(items)",
        "sum([[0] * 50] * 50, [])",
        "('x\\t' * 50).expandtabs(100)",
        "('x' * 100).translate({120: 'y' * 100})",
        "'%s' % items",
        "'%r' % items",
        "'%.0s' % items",
        "str(items.items())",
        "max([items], key=str)",
        "[items].sort(key=str)",
        "list.sort([items], key=str)",
    ],
)
def test_amplifying_operations_fail_before_an_oversized_result_exists(small_limits, expression):
    with pytest.raises(sandbox.ScriptSecurityError):
        sandbox.SafeAstInterpreter().evaluate_expression(
            expression, {"items": {"x": ["y" * 50] * 50}}
        )
    assert not any(size > 100 for size in small_limits)


@pytest.mark.parametrize(
    "code",
    [
        "items.append(1)",
        "items.extend([1])",
        "list.extend(items, [1])",
        "items.insert(0, 1)",
        "items[0:0] = [1]",
        "data.update({'extra': 1})",
        "dict.update(data, {'extra': 1})",
        "data['extra'] = 1",
        "data.setdefault('extra', 1)",
    ],
)
def test_container_growth_is_rejected_before_mutation(small_limits, code):
    context = {"items": [0] * 100, "data": {str(i): i for i in range(100)}}
    with pytest.raises(sandbox.ScriptSecurityError):
        sandbox.SafeAstInterpreter().execute(code, context)
    assert len(context["items"]) == len(context["data"]) == 100


def test_regular_formatting_and_mutation_remain_supported(small_limits):
    context = {}
    sandbox.SafeAstInterpreter().execute(
        "text = '%04d:%s' % (7, 'ok')\n"
        "values = [1]\nvalues.extend([2, 3])\nvalues[0:1] = [4]\n"
        "data = {'a': 1}\ndata.update({'a': 2, 'b': 3})\n"
        "joined = '-'.join(['a', 'b'])\n"
        "replaced = 'aaa'.replace('a', 'xy', 1)\n"
        "nested = str([['ok'], 2])\nflat = sum([[1], [2]], [])",
        context,
    )
    assert context["text"] == "0007:ok"
    assert context["values"] == [4, 2, 3]
    assert context["data"] == {"a": 2, "b": 3}
    assert context["joined"] == "a-b" and context["replaced"] == "xyaa"
    assert context["nested"] == "[['ok'], 2]" and context["flat"] == [1, 2]


@pytest.mark.parametrize(
    "mode", ["execute", "evaluate_expression", "check_syntax", "check_expression_syntax"]
)
def test_source_limit_applies_before_ast_parsing(monkeypatch, mode):
    monkeypatch.setattr(sandbox, "MAX_SOURCE_LENGTH", 20, raising=False)
    interpreter = sandbox.SafeAstInterpreter()
    source = "1" + " " * 21
    if mode.startswith("check_"):
        assert getattr(interpreter, mode)(source)
    else:
        with pytest.raises(sandbox.ScriptSecurityError):
            getattr(interpreter, mode)(source, {})


@pytest.mark.parametrize("call", ["api.set(items)", "api.value = items"])
def test_facade_payload_is_bounded_before_any_side_effect(small_limits, call):
    class Api:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    api = Api()
    context = {"api": api, "items": ["x" * 50] * 50}
    with pytest.raises(sandbox.ScriptSecurityError):
        sandbox.SafeAstInterpreter().execute(call, context)
    assert api.value is None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("b'%s' % data", b"x" * 100),
        ("str(data, 'ascii')", "x" * 100),
        ("dict(values, a=2)", {"a": 2, **{str(i): i for i in range(99)}}),
        ("str([[]])", "[[]]"),
        ("'%*.*s' % (-5, 2, 'long')", "lo   "),
        ("'%(name)s' % {'name': 'ok'}", "ok"),
    ],
)
def test_preflight_preserves_exact_limits_and_normal_semantics(small_limits, expression, expected):
    context = {"data": b"x" * 100, "values": {"a": 1, **{str(i): i for i in range(99)}}}
    assert sandbox.SafeAstInterpreter().evaluate_expression(expression, context) == expected


def test_recursive_list_has_bounded_representation(small_limits):
    items = []
    items.append(items)
    assert (
        sandbox.SafeAstInterpreter().evaluate_expression("str(items)", {"items": items})
        == "[[...]]"
    )


def test_short_empty_expression_remains_valid():
    assert sandbox.SafeAstInterpreter.check_expression_syntax(" \n ") == []


def test_native_key_callbacks_consume_the_instruction_budget(small_limits):
    with pytest.raises(sandbox.ScriptTimeoutError):
        sandbox.SafeAstInterpreter(max_steps=30).evaluate_expression(
            "max(values, key=len)", {"values": [[1]] * 80}
        )
