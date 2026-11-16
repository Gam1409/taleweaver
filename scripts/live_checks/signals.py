"""Read declared affect from decision envelopes, never infer it from prose keywords."""

import json


def decoded(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def decision(value) -> dict | None:
    value = decoded(value)
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("candidates"), (dict, list)) and isinstance(
        value.get("experiences"), list
    ):
        return value
    for request in value.get("requests", []) if isinstance(value.get("requests"), list) else []:
        if isinstance(request, dict) and request.get("name") == "submit_decision":
            return decision(request.get("arguments"))
    return None


def reported_affect(calls: list[dict]) -> list[str] | None:
    found = None
    for call in calls:
        choices = (call.get("response") or {}).get("choices", [])
        message = (choices[0].get("message") or {}) if choices else {}
        proposal = decision(message.get("content"))
        for item in message.get("tool_calls") or []:
            function = item.get("function", {})
            if function.get("name") == "submit_decision":
                proposal = decision(function.get("arguments")) or proposal
        if proposal is not None:
            found = sorted(
                {
                    value["dimension"]
                    for value in proposal["experiences"]
                    if isinstance(value, dict)
                    and value.get("channel") == "affect"
                    and value.get("level") != "absent"
                    and isinstance(value.get("dimension"), str)
                }
            )
    return found
