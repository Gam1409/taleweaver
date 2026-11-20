"""Optional admission check for player prose. Simulate earlier events on local copies only."""

import json
import re
from typing import Any

from backend.core.llm_router import GameMasterLLM
from backend.engine import prose_evidence
from backend.engine.chpm.control_settings import read
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.projection import known_worn_item_ids
from backend.engine.clothing.visuals import session_objects
from backend.engine.prose_evidence_catalog import visible_catalog
from backend.engine.turn_replay.service import pending_input
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot


def enabled(state: Any) -> bool:
    raw = (state.entity_states or {}).get("__chpm__")
    # The default path must not start validating unrelated legacy ledgers.
    fields = raw.get("settings") if isinstance(raw, dict) else None
    return bool(
        isinstance(fields, dict)
        and fields.get("reject_impossible_player_items") is True
        and read(raw).reject_impossible_player_items
    )


def contradiction(
    rows: list[dict], owners: dict[str, str], worn: dict[str, set[str]], names: dict[str, str]
) -> tuple[str, dict] | None:
    owners = dict(owners)
    worn = {actor: set(items) for actor, items in worn.items()}
    for row in rows:
        if not row["resolved"] or row["performer_id"] != PLAYER or not row["item_id"]:
            continue
        actor, item, value = row["actor_id"], row["item_id"], row["value"]
        if row["kind"] == "clothing":
            reason = _check_clothing(actor, item, value, owners, worn, names)
            if reason:
                return reason, row
        elif row["kind"] == "custody" and actor == PLAYER:
            if value in {"given", "placed"} and owners.get(item) != PLAYER:
                return "You do not have this item in your inventory.", row
            owners[item] = {"given": row["recipient_id"], "placed": SCENE, "picked_up": PLAYER}[
                value
            ]
            if value in {"given", "placed"}:
                worn.get(PLAYER, set()).discard(item)
    return None


def _check_clothing(
    actor: str,
    item: str,
    value: str,
    owners: dict[str, str],
    worn: dict[str, set[str]],
    names: dict[str, str],
) -> str | None:
    if value in {"removed", "partially_removed"} and actor in worn and item not in worn[actor]:
        return f"{names[actor]} is not wearing this item."
    if value == "worn" and actor == PLAYER and owners.get(item) != PLAYER:
        return "You do not have this item in your inventory."
    if actor in worn:
        if value == "removed":
            worn[actor].discard(item)
        else:
            worn[actor].add(item)
    return None


def error_event(reason: str, *, code: str, quote: str = "", retryable: bool = False) -> str:
    detail = f"{reason}\n“{quote}”" if quote else reason
    return (
        "event: error\ndata: "
        + json.dumps({"code": code, "detail": detail, "quote": quote, "retryable": retryable})
        + "\n\n"
    )


async def preflight(manager: Any, text: str) -> str | None:
    if (
        not enabled(manager.state)
        or getattr(manager, "_replaying", False)
        or await pending_input(manager, text) is not None
    ):
        return None
    entities = await session_objects(manager.db, manager.game_id)
    actors, items = visible_catalog(manager, entities)
    # An unknown noun cannot establish a contradiction. Skip inference altogether when
    # none of the player's words could bind to a unique known name.
    if not any(
        re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I)
        for name in items.values()
        if name
    ):
        return None
    if len(text) > prose_evidence.MAX_SOURCE:
        return error_event(
            "The action is too long for item checking. Split it into shorter turns.",
            code="item_check_unavailable",
        )
    # Only normal session initialization has run. Release its transaction before
    # the model call so a slow provider cannot block writers in other sessions.
    # The turn lease protects the captured inventory until admission finishes.
    await manager.db.commit()
    try:
        llm = GameMasterLLM.for_role(manager.user, "small")
        llm.enable_thinking = False
        llm.max_tokens = min(llm.max_tokens, 3000)
        result = await prose_evidence.review(
            llm,
            manager.game_id,
            {"role": "user", "content": text, "id": None, "revision_id": None},
            actors,
            items,
            player_check=True,
        )
    except Exception:
        return error_event(
            "Item checking is unavailable. Try this turn again.",
            code="item_check_unavailable",
            retryable=True,
        )
    # Incomplete extraction may have missed a prerequisite in the same turn. Never
    # use an incomplete sequence as proof that a later action was impossible.
    if result["discarded"] or not _ordered_item_events(result["events"]):
        return None
    return _check_result(manager, entities, result["events"], actors)


def _ordered_item_events(events: list[dict]) -> bool:
    # A single span can contain several actions in unknown order. Guessing their
    # sequence could reject a valid pickup followed by a handover.
    ends: dict[str, int] = {}
    for event in events:
        if event["kind"] not in {"custody", "clothing"}:
            continue
        if not event["resolved"] or not event["performer_id"]:
            return False
        item = event["item_id"]
        if event["start"] < ends.get(item, 0):
            return False
        ends[item] = event["end"]
    return True


def _check_result(
    manager: Any, entities: list, events: list[dict], actors: dict[str, str]
) -> str | None:
    records = actor_records(manager, entities)
    worn = {}
    for actor, record in records.items():
        known = known_worn_item_ids(
            record.get("visual_profile"),
            record["resolved_inventory"],
            equipment=record["equipment"],
        )
        if known is not None:
            worn[actor] = known
    problem = contradiction(events, possession_snapshot(manager, entities).owners, worn, actors)
    if problem:
        reason, row = problem
        return error_event(reason, code="impossible_player_item", quote=row["quote"])
    return None
