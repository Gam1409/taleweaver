"""Bound native operations before allocation or mutation, including unbound methods."""

from collections.abc import Callable, Mapping
from functools import partial
from types import ModuleType
from typing import Any

from backend.engine.scripting.errors import ScriptSecurityError
from backend.engine.scripting.text_budget import bounded, payload_size, text_size


def collect(values: Any, limit: int) -> list[Any]:
    result: list[Any] = []
    for value in values:
        bounded(len(result) + 1, limit)
        result.append(value)
    return result


def checked_sum(values: Any, start: Any = 0, *, limit: int) -> Any:
    items = collect(values, limit)
    if not isinstance(start, (list, tuple)):
        return sum(items, start)
    result = list(start)
    bounded(len(result), limit)
    for item in items:
        if not isinstance(item, type(start)):
            raise TypeError("sum() sequence elements must match the start type.")
        bounded(len(result) + len(item), limit)
        result.extend(item)
    return tuple(result) if isinstance(start, tuple) else result


def assignment(container: Any, key: Any, value: Any, limit: int) -> Any:
    if isinstance(container, dict):
        bounded(len(container) + int(key not in container), limit)
    elif isinstance(container, list) and isinstance(key, slice):
        inserted = collect(value, limit)
        removed = len(range(*key.indices(len(container))))
        bounded(len(container) - removed + len(inserted), limit)
        return inserted
    elif not isinstance(container, list):
        payload_size(value, limit)
    return value


def _binding(func: Any, args: list[Any]) -> tuple[Any, str, list[Any], int]:
    owner, name = getattr(func, "__self__", None), getattr(func, "__name__", "")
    if (
        owner is None
        and args
        and type(args[0]) in {str, bytes, list, tuple, dict}
        and getattr(type(args[0]), name, None) is func
    ):
        return args[0], name, args[1:], 1
    return owner, name, args, 0


def _join(owner: str | bytes, args: list[Any], limit: int) -> None:
    if len(args) != 1:
        return
    items = collect(args[0], limit)
    size = len(owner) * max(0, len(items) - 1)
    bounded(size, limit)
    for item in items:
        if isinstance(item, type(owner)):
            size = bounded(size + len(item), limit)
    args[0] = items


def _replace(owner: str | bytes, args: list[Any], limit: int) -> None:
    if len(args) < 2 or not all(isinstance(arg, type(owner)) for arg in args[:2]):
        return
    old, new = args[:2]
    count = args[2] if len(args) > 2 else -1
    if not isinstance(count, int):
        return
    matches = owner.count(old) if count < 0 else min(owner.count(old), count)
    bounded(len(owner) + matches * (len(new) - len(old)), limit)


def _translate(owner: str, args: list[Any], limit: int) -> None:
    if len(args) != 1:
        return
    if not isinstance(args[0], Mapping):
        raise ScriptSecurityError("translate() requires a bounded dictionary in scripts.")
    size = 0
    for char in owner:
        replacement = args[0].get(ord(char), char)
        size += (
            0 if replacement is None else len(replacement) if isinstance(replacement, str) else 1
        )
        bounded(size, limit)


def _update(owner: dict, args: list[Any], kwargs: dict[str, Any], limit: int) -> None:
    incoming: Mapping[Any, Any] = {}
    if args:
        incoming = args[0] if isinstance(args[0], Mapping) else dict(collect(args[0], limit))
        args[0] = incoming
    new_keys = set()
    for source in (incoming, kwargs):
        for key in source:
            if key not in owner:
                new_keys.add(key)
                bounded(len(owner) + len(new_keys), limit)


def _method(owner: Any, name: str, args: list[Any], kwargs: dict[str, Any], limit: int) -> None:
    bounded(len(owner), limit)
    if isinstance(owner, (str, bytes)):
        _string_method(owner, name, args, kwargs, limit)
    elif isinstance(owner, list):
        _list_method(owner, name, args, limit)
    elif isinstance(owner, dict):
        if name == "update":
            _update(owner, args, kwargs, limit)
        elif name == "setdefault" and args:
            assignment(owner, args[0], None, limit)


def _string_method(
    owner: str | bytes, name: str, args: list[Any], kwargs: dict[str, Any], limit: int
) -> None:
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, int):
            bounded(abs(arg), limit)
    if name == "join":
        _join(owner, args, limit)
    elif name == "replace":
        supplied = [*args[:2], kwargs.get("count", args[2] if len(args) > 2 else -1)]
        _replace(owner, supplied, limit)
    elif name == "expandtabs":
        width = args[0] if args else kwargs.get("tabsize", 8)
        if isinstance(width, int):
            tabs = owner.count(b"\t") if isinstance(owner, bytes) else owner.count("\t")
            bounded(len(owner) + tabs * max(0, width - 1), limit)
    elif name == "translate" and isinstance(owner, str):
        _translate(owner, args, limit)


def _list_method(owner: list, name: str, args: list[Any], limit: int) -> None:
    if name in {"append", "insert"}:
        bounded(len(owner) + 1, limit)
    elif name == "extend" and args:
        incoming = collect(args[0], limit)
        bounded(len(owner) + len(incoming), limit)
        args[0] = incoming


def _builtin(
    func: Any, args: list[Any], kwargs: dict[str, Any], limit: int, print_callable: Any
) -> Any:
    if func is str:
        value = args[0] if args else kwargs.get("object", "")
        if isinstance(value, bytes) and (len(args) > 1 or "encoding" in kwargs):
            bounded(len(value), limit)
        else:
            text_size(value, limit)
    elif func is sum:
        return partial(checked_sum, limit=limit)
    elif func is print_callable:
        _print_budget(args, kwargs, limit)
    elif func is dict:
        _update({}, args, kwargs, limit)
    elif func in (list, tuple) and args:
        args[0] = collect(args[0], limit)
    elif func is str.maketrans:
        for value in args:
            payload_size(value, limit)
    return func


def prepare(
    func: Any,
    args: list[Any],
    kwargs: dict[str, Any],
    limit: int,
    print_callable: Any,
    tick: Callable[[], None],
) -> tuple[Any, list[Any], dict[str, Any]]:
    func = _builtin(func, args, kwargs, limit, print_callable)
    owner, name, supplied, offset = _binding(func, args)
    if (func in (min, max) or isinstance(owner, list) and name == "sort") and kwargs.get("key"):
        kwargs["key"] = _checked_key(kwargs["key"], limit, print_callable, tick)
    if owner is dict and name == "fromkeys" and supplied:
        supplied[0] = collect(supplied[0], limit)
    if isinstance(owner, (str, bytes, list, tuple, dict)):
        _method(owner, name, supplied, kwargs, limit)
        args = [*args[:offset], *supplied] if offset else supplied
    elif owner is not None and not isinstance(owner, (type, ModuleType)):
        total = 0
        for value in (*args, *kwargs.values()):
            total = bounded(total + payload_size(value, max(0, limit - total)), limit)
    return func, args, kwargs


def _checked_key(
    key: Any, limit: int, print_callable: Any, tick: Callable[[], None]
) -> Callable[[Any], Any]:
    def invoke(value: Any) -> Any:
        tick()
        checked, args, kwargs = prepare(key, [value], {}, limit, print_callable, tick)
        return checked(*args, **kwargs)

    return invoke


def _print_budget(args: list[Any], kwargs: dict[str, Any], limit: int) -> None:
    separator = kwargs.get("sep", " ")
    if separator is None:
        separator = kwargs["sep"] = " "
    size = len(separator) * max(0, len(args) - 1)
    bounded(size, limit)
    for value in args:
        size = bounded(size + text_size(value, max(0, limit - size)), limit)
