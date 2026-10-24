"""Validate and materialize one bounded local scene before normal movement guards."""

import asyncio
import json
import logging
import unicodedata
from uuid import uuid4

from sqlalchemy import or_, select

from backend.core.llm_router import GameMasterLLM
from backend.engine.dynamic_locations.prompts import CONFIRM
from backend.engine.dynamic_locations.schema import (
    MAX_CHILDREN,
    MAX_DEPTH,
    MAX_PLACES,
    PlaceDecision,
    PlaceProposal,
    policy,
    registry,
    save_registry,
)
from backend.models.world_entity import WorldExit, WorldScene

logger = logging.getLogger(__name__)


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


async def _context(manager, proposal, user_msg, history, language):
    scenes = list(
        (
            await manager.db.scalars(
                select(WorldScene).where(
                    WorldScene.session_id == manager.game_id,
                )
            )
        ).all()
    )
    exits = list(
        (
            await manager.db.scalars(
                select(WorldExit).where(
                    WorldExit.session_id == manager.game_id,
                    or_(
                        WorldExit.from_scene_id == manager.state.current_scene_id,
                        WorldExit.to_scene_id == manager.state.current_scene_id,
                    ),
                )
            )
        ).all()
    )
    data = registry(manager.state)
    recent = "\n".join(str(m.get("content") or "") for m in history[-2:])[-6000:]
    context = {
        "content_language": language or "English",
        "player_action": user_msg,
        "proposal": proposal.model_dump(),
        "current_scene_id": manager.state.current_scene_id,
        "in_game_time": manager.state.in_game_time,
        "start_datetime": manager.state.start_datetime,
        "policy": policy(manager.state).model_dump(),
        "inferred_scale": data.get("inferred_scale"),
        "world_premise": str(manager.state.plot or manager.adventure.plot or "")[:4000],
        "rules": str(manager.state.rules or manager.adventure.rules or "")[:4000],
        "recent_narration": recent,
        "known_facts": (manager.state.world_memories or [])[-10:],
        "original_map": [
            {"id": s.id, "label": s.label} for s in scenes if s.id not in data.get("places", {})
        ][:80],
        "local_places": {
            sid: p
            for sid, p in data.get("places", {}).items()
            if p.get("parent_id") == manager.state.current_scene_id
        },
        "exits": [
            {"from": e.from_scene_id, "to": e.to_scene_id, "label": e.label, "locked": e.is_locked}
            for e in exits
        ],
    }
    current = next((s for s in scenes if s.id == manager.state.current_scene_id), None)
    context["current_description"] = current.description if current else ""
    return scenes, exits, context, recent


def _confirmed_arrival(decision, proposal, user_msg):
    return (
        decision.arrival_now
        and decision.player_moves
        and decision.local_to_current_scene
        and decision.access_allowed
        and not decision.contradicts_world
        and bool(proposal.action_quote.strip())
        and proposal.action_quote in user_msg
        and bool(decision.action_quote.strip())
        and decision.action_quote in user_msg
    )


def _eligible(decision, user_msg, recent, data, selected, parent_id):
    places = data.get("places") or {}
    depth = int(places.get(parent_id, {}).get("depth", 0)) + 1
    if depth > MAX_DEPTH or decision.granularity == "detail":
        return False
    scale = (
        selected.scale
        if selected.scale != "auto"
        else data.get("inferred_scale", decision.world_scale)
    )
    if scale == "regional" and decision.granularity == "room":
        return (
            decision.purpose != "ordinary"
            and bool(decision.purpose_quote.strip())
            and decision.purpose_quote in user_msg + "\n" + recent
        )
    # Do not nest whole buildings inside buildings on a regional map.
    return not (scale == "regional" and decision.granularity == "site" and depth > 1)


def _existing(decision, proposal, scenes, exits, data, parent):
    if decision.existing_scene_id:
        return decision.existing_scene_id
    names = {normalized(proposal.label), normalized(decision.label)} - {""}
    local_ids = {
        sid for sid, place in data.get("places", {}).items() if place.get("parent_id") == parent
    }
    local_ids.update(e.to_scene_id if e.from_scene_id == parent else e.from_scene_id for e in exits)
    return next((s.id for s in scenes if s.id in local_ids and normalized(s.label) in names), None)


def _open_exit(exits, current, target):
    return next(
        (
            e
            for e in exits
            if not e.is_locked
            and (
                (e.from_scene_id == current and e.to_scene_id == target)
                or (
                    e.exit_type == "bidirectional"
                    and e.to_scene_id == current
                    and e.from_scene_id == target
                )
            )
        ),
        None,
    )


async def materialize(manager, proposal, decision, user_msg, recent, scenes, exits) -> str | None:
    state = manager.state
    data = registry(state)
    selected = policy(state)
    parent = state.current_scene_id
    if not _confirmed_arrival(decision, proposal, user_msg):
        return None
    existing = _existing(decision, proposal, scenes, exits, data, parent)
    if existing:
        return existing if _open_exit(exits, parent, existing) else None
    if not _eligible(decision, user_msg, recent, data, selected, parent):
        return None
    places = dict(data.get("places") or {})
    if (
        len(places) >= MAX_PLACES
        or sum(p.get("parent_id") == parent for p in places.values()) >= MAX_CHILDREN
    ):
        return None
    if not decision.label.strip() or not decision.description.strip():
        return None
    scene_id = "dyn_" + uuid4().hex
    manager.db.add(
        WorldScene(
            id=scene_id,
            session_id=manager.game_id,
            label=decision.label.strip(),
            description=decision.description.strip(),
        )
    )
    manager.db.add(
        WorldExit(
            session_id=manager.game_id,
            from_scene_id=parent,
            to_scene_id=scene_id,
            label=decision.label.strip(),
            exit_type="bidirectional",
            is_locked=False,
        )
    )
    places[scene_id] = {
        "parent_id": parent,
        "label": decision.label,
        "depth": int(places.get(parent, {}).get("depth", 0)) + 1,
        "granularity": decision.granularity,
    }
    save_registry(
        state,
        {
            **data,
            "places": places,
            "inferred_scale": data.get("inferred_scale", decision.world_scale),
        },
    )
    await manager.db.flush()
    manager._dynamic_scene_images = [*getattr(manager, "_dynamic_scene_images", []), scene_id]
    return scene_id


async def resolve_proposal(manager, intent, user_msg, history, language) -> None:
    raw = getattr(intent, "new_local_place", None)
    if not raw or not policy(manager.state).enabled or intent.new_scene_id:
        return
    try:
        proposal = PlaceProposal.model_validate(raw)
        if proposal.action_quote not in user_msg:
            return
        scenes, exits, context, recent = await _context(
            manager, proposal, user_msg, history, language
        )
        llm = GameMasterLLM.for_role(manager.user, "small")
        decision = await asyncio.wait_for(
            llm.aexecute_complex_task(
                system_prompt=CONFIRM,
                user_prompt=json.dumps(context, ensure_ascii=False),
                response_model=PlaceDecision,
                model=llm.model,
                operation="chat_turn",
                phase="dynamic_location",
            ),
            timeout=90,
        )
        decision = PlaceDecision.model_validate(decision)
    except (ValueError, TimeoutError):
        logger.warning("Local place proposal rejected or timed out for session %s", manager.game_id)
        return
    except Exception:
        logger.exception("Local place generation failed for session %s", manager.game_id)
        return
    async with manager.db.begin_nested():
        intent.new_scene_id = await materialize(
            manager, proposal, decision, user_msg, recent, scenes, exits
        )


async def discard_unentered(manager) -> None:
    from backend.engine.dynamic_locations.lifecycle import prune

    ids = set(getattr(manager, "_dynamic_scene_images", []))
    removed = ids - {manager.state.current_scene_id}
    if not removed:
        return
    await prune(manager.db, manager.game_id, removed)
    data = registry(manager.state)
    save_registry(
        manager.state,
        {**data, "places": {k: v for k, v in data.get("places", {}).items() if k not in removed}},
    )
    manager._dynamic_scene_images = list(ids - removed)
