"""Owner-scoped optional dialogue pilot; no private trace in public NPC cards."""

from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_content_settings import _owned
from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.chpm import capacity
from backend.engine.chpm.schema import Contract, Settings, Usage
from backend.engine.chpm.state import KEY, load
from backend.engine.living_world.state import load as load_simulation
from backend.engine.visual_novel.presentation import known_character, session_is_vn
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from backend.models.world_entity import WorldEntity

router = APIRouter(tags=["CHPM"], dependencies=[Depends(session_mutation_lease)])


class Change(Contract):
    settings: Settings
    expected_revision: int = Field(ge=0, strict=True)


async def _characters(db: AsyncSession, state: SessionState) -> list[dict[str, str]]:
    rows = await db.scalars(
        select(WorldEntity)
        .where(WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC")
        .order_by(WorldEntity.id)
    )
    return [{"id": npc.id, "name": npc.name} for npc in rows if known_character(npc, state)]


async def _view(db: AsyncSession, state: SessionState, user: User) -> dict[str, Any]:
    current = load(state)
    return {
        "settings": current.settings.model_dump(),
        "revision": current.revision,
        "available": await session_is_vn(db, state),
        "characters": await _characters(db, state),
        "usage": current.usage.model_dump(),
        "memory_counts": {actor: len(entries) for actor, entries in current.memories.items()},
        "history_capacity": {
            actor: capacity.inspect(mind) for actor, mind in current.minds.items()
        },
        "required_call_budget": capacity.required_calls(current.settings),
        "psychology_counts": {
            actor: {
                "observations": len(mind.sources),
                "beliefs": len(mind.snapshot.beliefs),
            }
            for actor, mind in current.minds.items()
        },
        "psychology": {actor: mind.model_dump(mode="json") for actor, mind in current.minds.items()}
        if user.role == "admin"
        else {},
        "agenda_counts": {
            "active": sum(entry.closure is None for entry in current.agenda),
            "closed": sum(entry.closure is not None for entry in current.agenda),
        },
        "agenda": [entry.model_dump() for entry in current.agenda] if user.role == "admin" else [],
        "memory": {
            actor: [entry.model_dump() for entry in entries]
            for actor, entries in current.memories.items()
        }
        if user.role == "admin"
        else {},
        "trace": [value.model_dump() for value in current.actors.values()]
        if user.role == "admin"
        else [],
    }


@router.get("/{game_id}/chpm", response_model=None)
async def read(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    state, _ = await _owned(db, game_id, user)
    return await _view(db, state, user)


@router.patch("/{game_id}/chpm", response_model=None)
async def patch(
    game_id: str,
    payload: Change,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    state, before = await _owned(db, game_id, user)
    current = load(state)
    if current.revision != payload.expected_revision:
        raise HTTPException(409, "CHPM settings or state changed. Reload before saving.")
    if current.settings == payload.settings:
        return await _view(db, state, user)
    await _validate_change(db, state, payload.settings)
    replay = await db.get(TurnReplay, game_id)
    if replay is not None and replay.status in {"executing", "replaying"}:
        raise HTTPException(409, "Recover the unfinished turn before changing CHPM settings.")
    if (current.settings.mode, current.settings.actor_ids) != (
        payload.settings.mode,
        payload.settings.actor_ids,
    ):
        current.actors = {}
        current.memories = {}
        current.usage = Usage()
    current.settings = payload.settings
    current.revision += 1
    value = current.model_dump(mode="json")
    changed = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, cast(SessionState.entity_states, Text) == before)
        .values(entity_states={**(state.entity_states or {}), KEY: value})
        .returning(SessionState.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        raise HTTPException(409, "Session state changed. Reload before saving.")
    _update_replay(replay, value)
    await db.commit()
    await db.refresh(state)
    return await _view(db, state, user)


async def _validate_change(db: AsyncSession, state: SessionState, settings: Settings) -> None:
    if settings.mode == "off":
        return
    if not await session_is_vn(db, state):
        raise HTTPException(409, "The CHPM dialogue pilot supports Visual Novel sessions only.")
    required = capacity.required_calls(settings)
    if settings.max_calls_per_turn < required:
        raise HTTPException(
            422,
            f"The request budget must be at least {required}: perception, selected NPCs, "
            "and in live mode review plus one repair and repeat review.",
        )
    ids = {row["id"] for row in await _characters(db, state)}
    if not set(settings.actor_ids) <= ids:
        raise HTTPException(422, "Choose known NPCs from this session.")
    simulation = load_simulation(state)
    if settings.mode == "live" and simulation.settings.deliberation_enabled:
        raise HTTPException(
            409, "Disable Living World private decisions before enabling live CHPM."
        )


def _update_replay(replay: TurnReplay | None, value: dict) -> None:
    if replay is None:
        return
    before = deepcopy(replay.before)
    state = before.get("state") if isinstance(before, dict) else None
    if not isinstance(state, dict):
        raise HTTPException(409, "The turn snapshot is unavailable. Play a new turn first.")
    # Preserve the historical psychological state on budget-only changes. Mode
    # switches deliberately reinitialize the pilot, including the replay baseline.
    prior = (state.get("entity_states") or {}).get(KEY, {})
    same_mode = prior.get("settings", {}).get("mode", "off") == value["settings"]["mode"]
    same_actors = prior.get("settings", {}).get("actor_ids", []) == value["settings"]["actor_ids"]
    restored = {
        **value,
        "actors": prior.get("actors", {}) if same_mode and same_actors else {},
        "memories": prior.get("memories", {}) if same_mode and same_actors else {},
        # Never copy promises made in the completed turn into its retry baseline.
        "agenda": prior.get("agenda", []),
        # The current core may include observations from the completed reply.
        # Never transplant them into the replay's pre-turn snapshot, even on off/on.
        "minds": prior.get("minds", {}),
        "usage": Usage().model_dump(),
    }
    state["entity_states"] = {**(state.get("entity_states") or {}), KEY: restored}
    replay.before = before
