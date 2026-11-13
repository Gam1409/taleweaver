"""Validate and materialize one bounded local scene before normal movement guards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from pydantic import BaseModel

from backend.engine.dynamic_locations.schema import LocationPolicy

if TYPE_CHECKING:
    from backend.engine.gameplay.manager import GameTurnManager

import asyncio
import json
import logging
from uuid import uuid4

from sqlalchemy import or_, select

from backend.core.diagnostic_failures import failure_details, failure_reason
from backend.core.llm_router import GameMasterLLM
from backend.core.state_rejection_trace import reject
from backend.engine.dynamic_locations.companions import (
    bind_companions,
    finish_arrival,
    present_companions,
    record_arrival,
)
from backend.engine.dynamic_locations.identity import (
    place_catalog,
    request_clarification,
    resolve_identity,
)
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


class _SceneIntent(Protocol):
    new_scene_id: str | None


logger = logging.getLogger(__name__)


async def _context(
    manager: GameTurnManager,
    proposal: PlaceProposal,
    user_msg: str,
    history: list[dict[str, Any]],
    language: str | None,
) -> tuple[list[WorldScene], list[WorldExit], dict[str, Any], str]:
    if manager.state is None or manager.adventure is None:
        raise RuntimeError("Turn context must be initialized")
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
        "present_npcs": await present_companions(manager),
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
        "existing_place_catalog": place_catalog(
            scenes, exits, manager.state.current_scene_id, data
        ),
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


def _confirmed_arrival(decision: PlaceDecision, proposal: PlaceProposal, user_msg: str) -> bool:
    return (
        decision.arrival_now
        and decision.player_moves
        and decision.access_allowed
        and not decision.contradicts_world
        and bool(proposal.action_quote.strip())
        and proposal.action_quote in user_msg
        and bool(decision.action_quote.strip())
        and decision.action_quote in user_msg
    )


def _eligible(
    decision: PlaceDecision,
    user_msg: str,
    recent: str,
    data: dict[str, Any],
    selected: LocationPolicy,
    parent_id: str,
) -> bool:
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


def _open_exit(exits: list[WorldExit], current: str, target: str) -> WorldExit | None:
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


async def materialize(
    manager: GameTurnManager,
    proposal: PlaceProposal,
    decision: PlaceDecision,
    user_msg: str,
    recent: str,
    scenes: list[WorldScene],
    exits: list[WorldExit],
    *,
    catalog_complete: bool = True,
) -> str | None:
    state = manager.state
    if state is None:
        raise RuntimeError("Turn state must be initialized")
    data = registry(state)
    selected = policy(state)
    parent = state.current_scene_id
    if not _confirmed_arrival(decision, proposal, user_msg):
        return None
    identity = resolve_identity(decision, proposal, scenes, exits, data, parent)
    if identity.scene_id:
        return identity.scene_id if _open_exit(exits, parent, identity.scene_id) else None
    if (
        identity.uncertain
        or not catalog_complete
        or not decision.local_to_current_scene
        or not _eligible(decision, user_msg, recent, data, selected, parent)
    ):
        if identity.uncertain or not catalog_complete:
            request_clarification(manager, decision, scenes, exits)
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


async def resolve_proposal(
    manager: GameTurnManager,
    intent: BaseModel,
    user_msg: str,
    history: list[dict[str, Any]],
    language: str | None,
) -> None:
    if manager.state is None or manager.user is None:
        raise RuntimeError("Turn context must be initialized")
    manager._location_question = None
    raw = getattr(intent, "new_local_place", None)
    if not raw or not policy(manager.state).enabled or getattr(intent, "new_scene_id", None):
        return
    context: dict[str, Any] = {}
    decision: Any = None
    try:
        proposal = PlaceProposal.model_validate(raw)
        if proposal.action_quote not in user_msg:
            reject(
                "movement",
                "dynamic_location.source_mismatch",
                "The proposed arrival lacks exact evidence in the current player message.",
                proposal=raw,
                player_message=user_msg,
                history=history,
                source_context=manager.state.entity_states,
                session_id=manager.game_id,
            )
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
    except (ValueError, TimeoutError) as exc:
        reject(
            "movement",
            "dynamic_location.confirmation_timeout"
            if isinstance(exc, TimeoutError)
            else "dynamic_location.invalid_proposal",
            failure_reason(
                exc,
                "Local place confirmation timed out."
                if isinstance(exc, TimeoutError)
                else "Local place proposal failed validation.",
            ),
            proposal=raw,
            decision=decision,
            context=context,
            player_message=user_msg,
            history=history,
            source_context=manager.state.entity_states,
            session_id=manager.game_id,
            error_type=type(exc).__name__,
            **failure_details(exc),
        )
        logger.warning("Local place proposal rejected or timed out for session %s", manager.game_id)
        return
    except Exception as exc:
        reject(
            "movement",
            "dynamic_location.confirmation_failed",
            failure_reason(exc, "Local place generation failed."),
            proposal=raw,
            decision=decision,
            context=context,
            player_message=user_msg,
            history=history,
            source_context=manager.state.entity_states,
            session_id=manager.game_id,
            error_type=type(exc).__name__,
            **failure_details(exc),
        )
        logger.exception("Local place generation failed for session %s", manager.game_id)
        return
    async with manager.db.begin_nested():
        destination = await materialize(
            manager,
            proposal,
            decision,
            user_msg,
            recent,
            scenes,
            exits,
            catalog_complete=context["existing_place_catalog"]["complete"],
        )
        cast(_SceneIntent, intent).new_scene_id = destination
        bind_companions(intent, decision, destination, context, user_msg)
        record_arrival(manager, decision, destination, context, user_msg)


async def discard_unentered(manager: GameTurnManager) -> None:
    from backend.engine.dynamic_locations.lifecycle import prune

    if manager.state is None:
        raise RuntimeError("Turn state must be initialized")
    finish_arrival(manager)
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
