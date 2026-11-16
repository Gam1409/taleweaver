"""JSON equality keeps booleans distinct and compares numbers by value."""

from typing import Any


def json_equal(value: Any, expected: Any) -> bool:
    if type(value) in {int, float} and type(expected) in {int, float}:
        return bool(value == expected)
    if type(value) is not type(expected):
        return False
    if isinstance(value, list):
        return len(value) == len(expected) and all(
            json_equal(left, right) for left, right in zip(value, expected, strict=True)
        )
    if isinstance(value, dict):
        if value.keys() != expected.keys():
            return False
        return all(json_equal(item, expected[key]) for key, item in value.items())
    return bool(value == expected)
