"""Serialize canonical scripted intentions into the actual offered reference wire.

This is a test producer adapter, never a production response repair. Raw wire
rejection tests bypass it. Only literal, currently offered fragments can be selected;
invalid synthetic citations remain explicitly unavailable and must still reject.
"""

import json
from copy import deepcopy
from dataclasses import replace

from backend.engine.chpm import json_contract
from backend.engine.chpm.agent_limits import MAX_TOOL_ARGUMENT_CHARS


def evidence_text(row):
    return row.get("text", "\n".join(row.get("fragments", {}).values()))


def proposal(value, payload):
    if "reference_scope" not in payload or "reference_scope" in value:
        return value
    body = deepcopy(value)
    body["reference_scope"] = payload["reference_scope"]
    rows = payload["appraisal_context"]["visible_evidence"]
    visible = {row["source_id"]: row.get("fragments", {}) for row in rows}
    for key in ("new_beliefs", "belief_revisions", "experiences"):
        for item in body.get(key, []):
            item["citations"] = [_quote(citation, visible) for citation in item["citations"]]
    if isinstance(body.get("choice"), dict):
        body["choice"]["change_basis"] = [
            _quote(citation, visible) for citation in body["choice"].get("change_basis", [])
        ]
    for candidate in body.get("candidates", {}).values():
        candidate.setdefault("agenda_change", None)
        candidate.pop("goal_alignment", None)
        candidate.pop("goal_quote", None)
        _agenda(candidate.get("agenda_change"), payload)
    episodes = {
        item["episode_id"]: item["text"]
        for item in payload.get("development_context", {}).get("basis", [])
    }
    for development in body.get("developments", []):
        for key in ("citations", "counterexamples"):
            development[key] = [
                {"episode_id": item["episode_id"]}
                if set(item) == {"episode_id", "quote"}
                and item["quote"]
                and item["quote"] in episodes.get(item["episode_id"], "")
                else {**item, "episode_id": "unavailable-synthetic-episode"}
                for item in development.get(key, [])
            ]
    return body


def _quote(citation, visible):
    if set(citation) != {"source_id", "quote"}:
        return citation
    selected = next(
        (
            key
            for key, text in visible.get(citation.get("source_id"), {}).items()
            if citation.get("quote") and citation["quote"] in text
        ),
        "unavailable-synthetic-citation",
    )
    return {"fragment_id": selected}


def _agenda(intent, payload):
    if not intent:
        return
    if intent.get("entry_id") is None:
        intent.pop("entry_id", None)
        return
    active = payload.get("declared_agenda_not_world_facts", [])
    if any(
        entry["id"] == intent["entry_id"] and entry["text"] == intent.get("text")
        for entry in active
    ):
        intent.pop("text", None)


def response(raw, payload):
    body = _candidate(raw, payload)
    if body is None:
        return raw
    if "choice" in body and "candidates" in body:
        body = proposal(body, payload)
    for request in body.get("requests", []):
        if (
            isinstance(request, dict)
            and request.get("name") == "submit_decision"
            and isinstance(request.get("arguments"), dict)
        ):
            request["arguments"] = proposal(request["arguments"], payload)
    _review(body, payload)
    if payload.get("proposal_contract") == "goal-reference-v1" and "candidates" in body:
        body.setdefault("reference_scope", payload["reference_scope"])
        for candidate in body["candidates"].values():
            candidate.setdefault("agenda_change", None)
            quote = candidate.get("goal_quote", "")
            if quote and quote != payload["authored_goal"]:
                continue
            candidate.pop("goal_quote", None)
            candidate["goal_ref"] = (
                "authored_goal" if quote == payload["authored_goal"] and quote else None
            )
            _agenda(candidate.get("agenda_change"), payload)
    return json.dumps(body, ensure_ascii=False)


def _candidate(raw, payload):
    if not {"reference_scope", "review_scope"} & payload.keys():
        return None
    if not isinstance(raw, str) or len(raw) > MAX_TOOL_ARGUMENT_CHARS:
        return None
    try:
        return json_contract.decode(raw)
    except (ValueError, TypeError):
        return None


def _review(body, payload):
    if "passages" in payload and "agenda_evidence" in body:
        speech = {item["actor_id"]: item.get("passage_id") for item in body.get("evidence", [])}
        if all(
            speech.get(item["actor_id"]) == item.get("passage_id")
            for item in body["agenda_evidence"]
        ):
            body.pop("agenda_evidence")
    if "review_scope" in payload and "matches" in body and "review_scope" not in body:
        body["review_scope"] = payload["review_scope"]
        issues = body.pop("issues", [])
        body["rejections"] = [{"reason_code": "intention"} for _ in issues]


def tool_turn(result, messages):
    supplied = next((item["content"] for item in messages if item["role"] == "user"), None)
    if supplied is None:
        return result
    payload = json.loads(supplied)
    calls = tuple(
        replace(call, arguments_raw=response(call.arguments_raw, payload))
        if call.name == "submit_decision"
        else call
        for call in result.calls
    )
    message = deepcopy(result.assistant_message)
    if isinstance(message.get("content"), str):
        message["content"] = response(message["content"], payload)
    by_id = {call.id: call for call in calls}
    for call in message.get("tool_calls", []):
        if call.get("id") in by_id:
            call["function"]["arguments"] = by_id[call["id"]].arguments_raw
    return replace(result, calls=calls, assistant_message=message)
