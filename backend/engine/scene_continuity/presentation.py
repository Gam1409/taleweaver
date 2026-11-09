"""Audience projections share saved facts without sharing private causes or future state."""

import json
from typing import Any

from .ledger import digest, read
from .schema import Record


def _visible(row: Record, actor_id: str | None, targets: set[str] | None) -> bool:
    public_now = row.visibility == "public" and (
        row.status == "active" or actor_id is None or actor_id in row.observers
    )
    return (public_now or actor_id in row.observers) and (
        targets is None or row.subject_id in targets
    )


def project(
    state: Any,
    *,
    actor_id: str | None = None,
    targets: set[str] | None = None,
    scene_description: str | None = None,
    include_private: bool = False,
) -> dict:
    try:
        ledger = read(getattr(state, "entity_states", None))
    except ValueError:
        return {"status": "unavailable", "facts": []}
    minute = max(0, int(getattr(state, "in_game_time", 0) or 0))
    rows = [
        row
        for row in ledger.records.values()
        if row.scene_id == state.current_scene_id
        and (include_private or _visible(row, actor_id, targets))
    ]
    known = {row.id for row in rows if row.status != "unconfirmed"}
    result = []
    for row in sorted(
        rows, key=lambda row: (row.kind == "environment", -row.updated_minute, row.id)
    ):
        outdated = _outdated_environment(row, scene_description)
        if outdated and not include_private:
            continue
        item = {
            "id": row.id,
            "subject_id": row.subject_id,
            "kind": row.kind,
            "detail": row.detail,
            "status": row.status,
            "recorded_minute": row.recorded_minute,
            "updated_minute": row.updated_minute,
        }
        if outdated:
            item["status"] = "needs_confirmation"
        if (
            row.status == "active"
            and row.review_at_minute is not None
            and minute >= row.review_at_minute
        ):
            item["status"] = "needs_confirmation"
        if row.cause_id in known:
            item["cause_id"] = row.cause_id
        result.append(item)
    selected: list[dict[str, Any]] = []
    for item in result:
        if len(json.dumps([*selected, item], ensure_ascii=False)) > 10000:
            break
        selected.append(item)
    return {"status": "available", "facts": selected, "omitted": len(result) - len(selected)}


def _outdated_environment(row: Record, scene_description: str | None) -> bool:
    return (
        row.latest.kind == "scene_description"
        and scene_description is not None
        and row.latest.content_hash != digest(scene_description)
    )


def narration_block(state: Any, targets: set[str], scene_description: str) -> str:
    data = project(
        state, actor_id="__player__", targets=targets, scene_description=scene_description
    )
    if not data.get("facts") and data["status"] == "available":
        return ""
    return (
        "\nCURRENT SCENE CONTINUITY (saved facts, not NPC intentions):\n"
        + json.dumps(data, ensure_ascii=False)
        + "\nSilence does not end active processes or remove their effects. Ended processes are past events, "
        "not ongoing actions. Needs-confirmation facts must not be asserted as still ongoing. "
        "An ended cause does not resolve a remaining consequence. Private causes are not shared knowledge. "
        "These facts do not authorize movement, transfers, exposure or mechanical changes.\n"
    )


def visual_facts(state: Any, targets: set[str], scene_description: str, message_id: str) -> dict:
    try:
        ledger = read(state.entity_states)
    except ValueError:
        return {}
    projected = project(state, targets=targets, scene_description=scene_description)
    active = {row["id"] for row in projected["facts"] if row["status"] == "active"}
    facts = [
        {"id": row.id, "subject_id": row.subject_id, "kind": row.kind, "detail": row.visual_detail}
        for row in ledger.records.values()
        if row.id in active and row.visual_detail and row.visibility == "public"
    ][:16]
    actions = ledger.frame_actions if ledger.frame_message_id == message_id else []
    actions = [row for row in actions if set(row.actor_ids).issubset(targets)]
    return {
        "scene_facts": facts,
        "visible_action": "; ".join(row.detail for row in actions),
        "visible_actions": [row.model_dump(exclude={"evidence"}) for row in actions],
    }
