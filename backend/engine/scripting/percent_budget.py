"""Preflight percent conversions independently before constructing their aggregate."""

import re
from typing import Any

from backend.engine.scripting.errors import ScriptSecurityError
from backend.engine.scripting.text_budget import bounded, text_size

_FIELD = re.compile(r"%(?:\(([^)]+)\))?([#0\- +]*)(\*|\d+)?(?:\.(\*|\d*))?([diouxXeEfFgGcrsab%])")


def _number(raw: str | None, limit: int) -> int | None:
    if raw is None:
        return None
    digits = raw.lstrip("0") or "0"
    if len(digits) > len(str(limit)):
        raise ScriptSecurityError("Format width or precision exceeds the safe limit.")
    return bounded(int(digits), limit)


class _Arguments:
    def __init__(self, value: Any, limit: int) -> None:
        self.value = value
        self.positional = value if isinstance(value, tuple) else (value,)
        self.index = 0
        self.limit = limit

    def next(self) -> Any:
        if self.index >= len(self.positional):
            raise TypeError("Not enough arguments for the format string.")
        result = self.positional[self.index]
        self.index += 1
        return result

    def dimension(self, raw: str | None) -> int | None:
        if raw != "*":
            return _number(raw, self.limit)
        value = self.next()
        if not isinstance(value, int):
            raise TypeError("Format width and precision require integers.")
        bounded(abs(value), self.limit)
        return value


def check_percent(template: str | bytes, values: Any, limit: int) -> None:
    text = template.decode("latin1") if isinstance(template, bytes) else template
    bounded(len(text), limit)
    arguments = _Arguments(values, limit)
    cursor = total = work = 0
    while cursor < len(text):
        start = text.find("%", cursor)
        if start < 0:
            bounded(total + len(text) - cursor, limit)
            return
        total += start - cursor
        if text.startswith("%%", start):
            total = bounded(total + 1, limit)
            cursor = start + 2
            continue
        match = _FIELD.match(text, start)
        if match is None or match[5] == "%":
            raise ValueError("Unsupported percent format in script.")
        size, cost = _field_size(match, arguments, template, max(0, limit - work))
        total = bounded(total + size, limit)
        work = bounded(work + cost, limit)
        cursor = match.end()


def _field_size(
    match: re.Match[str], arguments: _Arguments, template: str | bytes, remaining: int
) -> tuple[int, int]:
    key, flags, width_spec, precision_spec, kind = match.groups()
    width = arguments.dimension(width_spec)
    precision = arguments.dimension(precision_spec)
    if key is not None:
        if not isinstance(arguments.value, dict):
            raise TypeError("Mapped formats require a dictionary in scripts.")
        lookup = key.encode("latin1") if isinstance(template, bytes) else key
        value = arguments.value[lookup]
    else:
        value = arguments.next()
    # CPython renders containers before applying a precision truncation. Bound
    # that intermediate work too, even if the final field would be empty.
    cost = (
        bounded(len(value), remaining)
        if isinstance(template, bytes) and isinstance(value, bytes) and kind in {"s", "b"}
        else text_size(value, remaining, representation=kind in {"r", "a"}, ascii_only=kind == "a")
    )
    if width is not None and width < 0:
        flags += "-"
    spec = "%" + flags + (str(abs(width)) if width is not None else "")
    if precision is not None:
        spec += "." + str(max(0, precision))
    spec += kind
    token: str | bytes = spec.encode("ascii") if isinstance(template, bytes) else spec
    # Each field has bounded width/precision and a bounded source. A single
    # numeric conversion may add a small exponent/sign overhead; it cannot
    # amplify the whole argument list before the aggregate budget check.
    rendered = token % (value,)
    return len(rendered), cost
