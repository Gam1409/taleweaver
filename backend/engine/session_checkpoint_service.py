from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.checkpoint_avatar import restore as restore_avatar
from backend.engine.checkpoint_world import capture as capture_world
from backend.engine.checkpoint_world import restore as restore_world
from backend.engine.checkpoint_world import validate as validate_world
from backend.engine.chpm import recovery_queue
from backend.engine.chpm.lifecycle import validate as validate_chpm
from backend.engine.clothing.lifecycle import (
    CHECKPOINT_KEY,
    capture_item_ids,
    rewind_created_garments,
)
from backend.engine.dynamic_locations.lifecycle import rewind as rewind_places
from backend.engine.dynamic_locations.schema import registry
from backend.engine.living_world.state import fork as fork_simulation
from backend.engine.living_world.state import offline_total
from backend.engine.memory_rag.lifecycle import invalidate_memory, memory_snapshot, restore_memory
from backend.engine.npc_journal.lifecycle import rewind_journals
from backend.engine.visual_plan_lifecycle import reset, without_cache
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.schemas.checkpoint import SessionCheckpointResponse

MAX_CHECKPOINTS_PER_SESSION = 5
MAX_DEBUG_CHECKPOINTS_PER_SESSION = 5
DEBUG_TURN_REASON = "DEBUG_TURN"


def _reason_title(reason: str, snapshot: dict[str, Any]) -> str:
    scene_label = str(snapshot.get("scene_label") or "").strip()
    norm = str(reason or "").upper()
    if norm == DEBUG_TURN_REASON:
        number = _debug_details(snapshot)["turn_number"]
        return f"Debug: Before turn {number}" if number else "Debug: Before turn"
    if norm == "SCENE_CHANGE":
        return (
            f"Checkpoint: Arrived at {scene_label}" if scene_label else "Checkpoint: Scene Changed"
        )
    if norm == "QUEST_UPDATE":
        return "Checkpoint: Quest Update"
    if norm == "AWARD_GRANTED":
        return "Checkpoint: Award Granted"
    if "WORLD_MEMOR" in norm:
        return "Checkpoint: World Memory Updated"
    return f"Checkpoint: {reason.replace('_', ' ').title()}" if reason else "Checkpoint"


def _debug_details(snapshot: dict[str, Any]) -> dict:
    info = snapshot.get("debug_turn") or {}
    if not isinstance(info, dict):
        return {"turn_number": None, "input_preview": None}
    number, preview = info.get("turn_number"), info.get("input_preview")
    return {
        "turn_number": number if type(number) is int and number > 0 else None,
        "input_preview": preview[:160] if isinstance(preview, str) else None,
    }


def _restore_session_context(
    game_session: GameSession, state: SessionState, snapshot: dict[str, Any]
) -> None:
    state_snapshot = snapshot.get("session_state") or {}
    if "active_sequence_id" in state_snapshot:
        state.active_sequence_id = state_snapshot["active_sequence_id"]
    game_session.status = snapshot.get("session_status") or (
        "completed" if state.is_completed else "active"
    )


class SessionCheckpointService:
    @staticmethod
    async def _load_context(
        db: AsyncSession, session_id: str
    ) -> tuple[GameSession, SessionState, Avatar]:
        session_res = await db.execute(select(GameSession).where(GameSession.id == session_id))
        game_session = session_res.scalars().first()
        if not game_session:
            raise ValueError("Session not found.")

        state_res = await db.execute(
            select(SessionState).where(SessionState.session_id == session_id)
        )
        state = state_res.scalars().first()
        if not state:
            raise ValueError("Session state not found.")

        avatar_res = await db.execute(select(Avatar).where(Avatar.id == state.avatar_id))
        avatar = avatar_res.scalars().first()
        if not avatar:
            raise ValueError("Session avatar not found.")

        return game_session, state, avatar

    @staticmethod
    async def _message_ids(db: AsyncSession, session_id: str) -> list[str]:
        msg_res = await db.execute(
            select(ChatMessage.id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
        return list(msg_res.scalars().all())

    @staticmethod
    def _build_snapshot(
        state: SessionState, avatar: Avatar, scene_label: str | None = None
    ) -> dict[str, Any]:
        return {
            "avatar": {
                "hp": avatar.hp,
                "max_hp": avatar.max_hp,
                "stamina": avatar.stamina,
                "max_stamina": avatar.max_stamina,
                "mana": avatar.mana,
                "max_mana": avatar.max_mana,
                "exp": avatar.exp,
                "strength": avatar.strength,
                "intelligence": avatar.intelligence,
                "wisdom": avatar.wisdom,
                "dexterity": avatar.dexterity,
                "charisma": avatar.charisma,
                "armor_class": avatar.armor_class,
                "stats": deepcopy(avatar.stats or {}),
                "inventory": deepcopy(avatar.inventory or []),
                "equipment": deepcopy(avatar.equipment or {}),
                "gender": avatar.gender,
                "age_years": avatar.age_years,
                "visual_profile": deepcopy(avatar.visual_profile),
                "status_effects": deepcopy(avatar.status_effects or []),
            },
            "session_state": {
                **memory_snapshot(state),
                "current_scene_id": state.current_scene_id,
                "active_sequence_id": state.active_sequence_id,
                "in_game_time": state.in_game_time,
                "time_system": state.time_system,
                "time_config": deepcopy(state.time_config or {}),
                "inventory": deepcopy(state.inventory or []),
                "entity_states": without_cache(state.entity_states),
                "living_world": deepcopy(state.living_world),
                "exit_states": deepcopy(state.exit_states or {}),
                "discovered_scenes": deepcopy(state.discovered_scenes or []),
                "quests": deepcopy(state.quests or []),
                "is_completed": bool(state.is_completed),
                "scene_label": scene_label,
            },
            "scene_label": scene_label,
        }

    @staticmethod
    async def _prune_old_checkpoints(
        db: AsyncSession, session_id: str, keep: int = MAX_CHECKPOINTS_PER_SESSION
    ) -> None:
        cp_res = await db.execute(
            select(SessionCheckpoint)
            .where(SessionCheckpoint.session_id == session_id)
            .order_by(SessionCheckpoint.created_at.desc(), SessionCheckpoint.id.desc())
        )
        points = [
            cp
            for cp in cp_res.scalars().all()
            if cp.trigger_reason.upper() != "MANUAL"
            and not (cp.state_snapshot or {}).get("pinned", False)
        ]
        ordinary = [cp.id for cp in points if cp.trigger_reason.upper() != DEBUG_TURN_REASON]
        debug = [cp.id for cp in points if cp.trigger_reason.upper() == DEBUG_TURN_REASON]
        stale_ids = ordinary[keep:] + debug[MAX_DEBUG_CHECKPOINTS_PER_SESSION:]
        if stale_ids:
            await db.execute(delete(SessionCheckpoint).where(SessionCheckpoint.id.in_(stale_ids)))

    @staticmethod
    async def create_checkpoint(
        db: AsyncSession,
        session_id: str,
        trigger_reason: str,
        scene_label: str | None = None,
    ) -> SessionCheckpoint:
        game_session, state, avatar = await SessionCheckpointService._load_context(db, session_id)
        message_ids = await SessionCheckpointService._message_ids(db, session_id)

        snapshot = SessionCheckpointService._build_snapshot(state, avatar, scene_label=scene_label)
        snapshot["session_status"] = game_session.status
        snapshot["npc_recovery"] = await recovery_queue.capture(db, session_id)
        snapshot.update(await capture_world(db, state))
        snapshot[CHECKPOINT_KEY] = await capture_item_ids(db, session_id, snapshot)
        payload = jsonable_encoder(snapshot)

        checkpoint = SessionCheckpoint(
            session_id=session_id,
            message_index=len(message_ids),
            state_snapshot=payload,
            trigger_reason=trigger_reason,
        )
        db.add(checkpoint)
        await db.flush()

        await SessionCheckpointService._prune_old_checkpoints(db, session_id)
        return checkpoint

    @staticmethod
    async def list_checkpoints(
        db: AsyncSession, session_id: str
    ) -> list[SessionCheckpointResponse]:
        cp_res = await db.execute(
            select(SessionCheckpoint)
            .where(SessionCheckpoint.session_id == session_id)
            .order_by(SessionCheckpoint.created_at.desc(), SessionCheckpoint.id.desc())
        )
        checkpoints = list(cp_res.scalars().all())
        return [
            SessionCheckpointResponse(
                id=cp.id,
                session_id=cp.session_id,
                message_index=cp.message_index,
                pinned=bool((cp.state_snapshot or {}).get("pinned")),
                trigger_reason=cp.trigger_reason,
                title=_reason_title(cp.trigger_reason, cp.state_snapshot or {}),
                created_at=cp.created_at,
                **_debug_details(cp.state_snapshot or {}),
            )
            for cp in checkpoints
        ]

    @staticmethod
    async def restore_checkpoint(
        db: AsyncSession, session_id: str, checkpoint_id: str, *, warnings: list[str] | None = None
    ) -> int:
        cp_res = await db.execute(
            select(SessionCheckpoint).where(
                SessionCheckpoint.id == checkpoint_id,
                SessionCheckpoint.session_id == session_id,
            )
        )
        checkpoint = cp_res.scalars().first()
        if not checkpoint:
            raise ValueError("Checkpoint not found.")

        game_session, state, avatar = await SessionCheckpointService._load_context(db, session_id)
        snapshot = checkpoint.state_snapshot or {}
        validate_world(snapshot)
        if warnings is not None and (
            "canonical_items" not in snapshot or "canonical_actors" not in snapshot
        ):
            warnings.append(
                "This older checkpoint lacks complete canonical item/NPC snapshots. "
                "Only stored fields can be recovered; unsaved canonical fields are retained."
            )
        avatar_snapshot = snapshot.get("avatar") or {}
        state_snapshot = snapshot.get("session_state") or {}
        restored_entities = deepcopy(validate_chpm(state_snapshot.get("entity_states"), session_id))

        restore_avatar(avatar, avatar_snapshot)

        state.current_scene_id = str(
            state_snapshot.get("current_scene_id") or state.current_scene_id
        )
        state.in_game_time = int(state_snapshot.get("in_game_time", state.in_game_time or 0))
        state.time_system = str(state_snapshot.get("time_system") or state.time_system)
        state.time_config = deepcopy(state_snapshot.get("time_config") or {})
        state.inventory = deepcopy(state_snapshot.get("inventory") or [])
        previous_places = deepcopy(registry(state))
        restored_entities.pop("__portrait_requests__", None)
        state.entity_states = reset(restored_entities)
        state.living_world = fork_simulation(
            state_snapshot.get("living_world"),
            absence_total=offline_total(game_session.living_world_presence),
        )
        await rewind_places(db, state, previous_places)
        state.exit_states = deepcopy(state_snapshot.get("exit_states") or {})
        state.discovered_scenes = deepcopy(state_snapshot.get("discovered_scenes") or [])
        state.quests = deepcopy(state_snapshot.get("quests") or [])
        state.is_completed = bool(state_snapshot.get("is_completed", state.is_completed))
        _restore_session_context(game_session, state, snapshot)
        await restore_world(db, state, snapshot)
        restore_memory(state, state_snapshot)
        await invalidate_memory(db, session_id)

        message_ids = await SessionCheckpointService._message_ids(db, session_id)
        stale_ids = message_ids[checkpoint.message_index :]
        await rewind_created_garments(db, session_id, snapshot, stale_ids)
        if stale_ids:
            await rewind_journals(db, session_id, stale_ids)
            await db.execute(delete(ChatMessage).where(ChatMessage.id.in_(stale_ids)))
        await recovery_queue.restore(db, session_id, snapshot.get("npc_recovery") or {})

        await db.execute(
            delete(SessionCheckpoint)
            .where(
                SessionCheckpoint.session_id == session_id,
                SessionCheckpoint.id != checkpoint_id,
                or_(
                    SessionCheckpoint.message_index > checkpoint.message_index,
                    SessionCheckpoint.created_at > checkpoint.created_at,
                    and_(
                        SessionCheckpoint.created_at == checkpoint.created_at,
                        SessionCheckpoint.id > checkpoint.id,
                    ),
                ),
            )
            .execution_options(synchronize_session="fetch")
        )
        await db.execute(delete(TurnReplay).where(TurnReplay.session_id == session_id))
        if "__agent__" in (state.entity_states or {}):
            from backend.engine.gameplay.agent_logic import AgentService

            AgentService.set_agent_active(state, False)

        return len(stale_ids)
