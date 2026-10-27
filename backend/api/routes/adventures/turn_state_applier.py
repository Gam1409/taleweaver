from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.turn_event_awards import TurnEventAwards
from backend.api.routes.adventures.turn_event_entities import TurnEventEntities
from backend.api.routes.adventures.turn_event_inventory import TurnEventInventory
from backend.api.routes.adventures.turn_event_inventory_hooks import TurnEventInventoryHooks
from backend.api.routes.adventures.turn_event_progression import TurnEventProgression
from backend.api.routes.adventures.turn_event_scenes import TurnEventScenes
from backend.api.routes.adventures.turn_event_world import TurnEventWorld
from backend.core.game_modes import is_vn
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.map_engine import MapEngine
from backend.engine.mutation_targets import validate_mutation_targets
from backend.engine.quest_manager import QuestManager
from backend.engine.rule_engine import (
    EntityMovement,
    GameEvent,
    WorldEntityUpdate,
)
from backend.engine.visual_novel.event_policy import enforce_vn_event_policy
from backend.engine.visual_novel.ownership import sync_vn_ownership
from backend.models.world_entity import WorldExit

if TYPE_CHECKING:
    from backend.api.routes.adventures.gameplay_logic import GameTurnManager

__all__ = ["QuestManager", "TurnStateApplier"]

CHECKPOINT_REASON_SCENE_CHANGE = "SCENE_CHANGE"
CHECKPOINT_REASON_QUEST_UPDATE = "QUEST_UPDATE"
CHECKPOINT_REASON_AWARD_GRANTED = "AWARD_GRANTED"


class TurnStateApplier(
    TurnEventInventory,
    TurnEventInventoryHooks,
    TurnEventScenes,
    TurnEventEntities,
    TurnEventProgression,
    TurnEventAwards,
    TurnEventWorld,
):
    """Applies game event outcomes to the database, session state, entities, inventory, and awards."""

    def __init__(self, manager: GameTurnManager) -> None:
        self.manager = manager

    @property
    def db(self):
        return self.manager.db

    @property
    def game_id(self):
        return self.manager.game_id

    @property
    def user(self):
        return self.manager.user

    @property
    def state(self):
        return self.manager.state

    @property
    def avatar(self):
        return self.manager.avatar

    @property
    def adventure(self):
        return self.manager.adventure

    def _queue_checkpoint(self, *args, **kwargs):
        return self.manager._queue_checkpoint(*args, **kwargs)

    async def _save_chat_message(self, *args, **kwargs):
        return await self.manager._save_chat_message(*args, **kwargs)

    def _apply_gm_notes_update(self, *args, **kwargs):
        return self.manager._apply_gm_notes_update(*args, **kwargs)

    def _award_combat_victory_xp(self, *args, **kwargs):
        return self.manager._award_combat_victory_xp(*args, **kwargs)

    def _collect_existing_item_ids(self, *args, **kwargs):
        return self.manager._collect_existing_item_ids(*args, **kwargs)

    async def _spawn_scene_item(self, *args, **kwargs):
        return await self.manager._spawn_scene_item(*args, **kwargs)

    async def _apply_adventure_generator_tools(self, *args, **kwargs):
        return await self.manager._apply_adventure_generator_tools(*args, **kwargs)

    def _upsert_entity_update(self, event: GameEvent, entity_id: str, **fields: object) -> None:
        """Insert or merge a WorldEntityUpdate for ``entity_id`` into the event."""
        if not entity_id:
            return
        if event.updated_entities is None:
            event.updated_entities = []
        for up in event.updated_entities:
            if up.entity_id == entity_id:
                for key, value in fields.items():
                    setattr(up, key, value)
                return
        event.updated_entities.append(WorldEntityUpdate(entity_id=entity_id, **fields))  # type: ignore[arg-type]

    def _upsert_entity_movement(self, event: GameEvent, entity_id: str, to_scene_id: str) -> None:
        """Insert or merge an EntityMovement for ``entity_id`` into the event."""
        if not entity_id or not to_scene_id:
            return
        if event.moved_entities is None:
            event.moved_entities = []
        for move in event.moved_entities:
            if move.entity_id == entity_id:
                move.to_scene_id = to_scene_id
                return
        event.moved_entities.append(EntityMovement(entity_id=entity_id, to_scene_id=to_scene_id))

    async def _build_map_payload(self) -> dict:
        """Helper to build the augmented map payload for the frontend."""
        world_map = await AdventureLogic.get_or_create_map(self.db, self.state.template_id)
        if not world_map:
            return {"nodes": {}, "edges": [], "current_scene_id": None}

        map_dict = MapEngine.to_dict(world_map)
        map_dict["current_scene_id"] = MapEngine._safe_id(self.state.current_scene_id)
        # Heal stale image_url values (e.g. from deleted sessions) in the map nodes
        for node in map_dict.get("nodes", {}).values():
            if isinstance(node, dict) and node.get("image_url"):
                node["image_url"] = AdventureLogic.resolve_existing_data_asset_url(
                    node["image_url"]
                )

        # Augment with adjacent unvisited scenes
        # Fetch exits for this session or template
        exit_query = select(WorldExit).where(
            or_(
                WorldExit.session_id == self.state.session_id,
                WorldExit.template_id == self.state.template_id,
            )
        )
        exits_res = await self.db.execute(exit_query)
        exits = list(exits_res.scalars().all())
        map_dict = MapEngine.augment_map_data(map_dict, exits, self.state.current_scene_id)

        return map_dict

    async def _apply_game_event(self, event: GameEvent) -> list[str]:
        """Applies technical mutations from a GameEvent to the database and session state. Returns messages for the UI."""
        enforce_vn_event_policy(event, self.adventure)
        await validate_mutation_targets(self.manager, event)
        vn_mode = is_vn(self.adventure)
        system_messages: list[str] = []
        states = dict(self.state.entity_states or {})
        await self._prepare_inventory_items(event, vn_mode)

        await self._apply_avatar_outcomes(event, system_messages)

        state_dirty = False
        state_dirty |= await self._apply_scene_transition(event, states, system_messages)

        # Entity State Overrides (Movement, Stats, Visibility)
        states = dict(self.state.entity_states or {})

        state_dirty |= await self._apply_entity_movements(event, states, system_messages)

        state_dirty |= await self._apply_entity_updates(event, states, system_messages, vn_mode)

        if event.deleted_entities:
            for eid in event.deleted_entities:
                if eid not in states:
                    states[eid] = {}
                states[eid]["is_hidden"] = True
                state_dirty = True

        state_dirty |= await self._apply_inventory_hooks(event, states, system_messages)

        if event.spawned_items and not vn_mode:
            for item in event.spawned_items:
                await self._spawn_scene_item(item.model_dump(exclude_none=True))
            state_dirty = True

        if event.remember_notes or event.forget_notes or event.clear_notes:
            self._apply_gm_notes_update(
                event.remember_notes, event.forget_notes, bool(event.clear_notes)
            )

        progression_dirty, newly_completed_quests = await self._apply_explicit_progression(
            event, system_messages, vn_mode
        )
        state_dirty |= progression_dirty

        script_context = await self._progression_script_context()

        # Deterministic Award Evaluation for awards configured with hard rules
        det_award_msgs = await self._evaluate_deterministic_awards(event, script_context)
        system_messages.extend(det_award_msgs)

        state_dirty |= await self._apply_deterministic_quests(
            event, system_messages, vn_mode, script_context, newly_completed_quests
        )

        state_dirty |= await self._apply_sequence_progression(
            event, system_messages, vn_mode, script_context
        )

        await self._apply_exit_updates(event, system_messages)

        if vn_mode:
            state_dirty |= await sync_vn_ownership(self.db, self.state, self.avatar, event, states)
            state_dirty |= await apply_wardrobe(self.manager, event, states)

        state_dirty |= await self._synchronize_npc_inventories(states)

        await self._apply_world_memories(event, system_messages)

        state_dirty |= await self._apply_turn_time(event, vn_mode)

        if state_dirty:
            self.state.entity_states = states
            flag_modified(self.state, "entity_states")

        await self._apply_adventure_generator_tools(event)
        await self.db.flush()
        return system_messages
