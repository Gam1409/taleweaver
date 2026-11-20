"""Real VN owner fixtures for an interrupted multi-step independent NPC choice."""

import json
from copy import deepcopy

from sqlalchemy import select

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.npc_actions import publication
from backend.engine.npc_actions.contracts import TakeOff
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity, WorldScene
from tests.test_clothing_runtime import item, profile
from tests.test_npc_two_phase_turn import CupRoles, seed

COAT = "SEQUENTIAL_COAT"
FIRST_STORY = "Лина сняла пальто и оставила его у себя. Лина: «Пока подержу его сама.»"
NEXT_STORY = "Лина: «Я ещё решу, как поступить дальше.»"
PLAN = [
    {"tool": "take_off_item", "item_id": COAT},
    {"tool": "give_item", "item_id": COAT, "recipient_id": "MILA"},
]


class SequentialRoles(CupRoles):
    """Choose a plan, then independently reconsider without being told a next action."""

    def __init__(self):
        super().__init__(deepcopy(PLAN))
        self.writer_requests = []

    @property
    def story(self):
        return FIRST_STORY if self.steps else NEXT_STORY

    def answer(self, payload, functions, phase, kwargs):
        result = super().answer(payload, functions, phase, kwargs)
        if phase == "npc_execution":
            return result
        selected = result[0][1]
        selected["candidates"]["REFUSE"]["intention"] = (
            "Remove my coat and hand it to Mila."
            if self.steps
            else "Reconsider my own plan using what I can currently observe."
        )
        return result

    async def stream(self, *args, **kwargs):
        self.writer_requests.append(deepcopy((args, kwargs)))
        return await super().stream(*args, **kwargs)


async def seed_sequential(db, protocol):
    user, state = await seed(db, protocol, pair=False)
    lina = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    lina.inventory, lina.visual_profile = [item(COAT)], profile(COAT)
    mila = await db.scalar(select(WorldEntity).where(WorldEntity.id == "MILA"))
    mila.moveable = True
    mila.spatial_position = "at the far doorway"
    mila.goal = "PRIVATE_DESTINATION_MUST_NOT_LEAK"
    db.add(
        WorldScene(
            id="ANNEX", session_id=state.session_id, label="Annex", description="A quiet annex."
        )
    )
    await db.commit()
    return user, state


async def owner_state(host):
    rows = await session_objects(host.db, host.game_id)
    actors = actor_records(host, rows)
    worn = load_profile(actors["LINA"]["visual_profile"]).worn
    return possession_snapshot(host, rows).owners[COAT], {row.item_id for row in worn}


def interrupt_after_removal(monkeypatch):
    """An unrelated real owner moves the recipient between two publication steps."""
    original = publication._apply
    completed = []

    async def apply(host, scope, request, preview):
        await original(host, scope, request, preview)
        completed.append(request.tool)
        if not isinstance(request, TakeOff):
            return
        assert await owner_state(host) == ("LINA", set())
        before = host.state.current_scene_id, host.state.in_game_time
        await TurnStateApplier(host).apply_narrated_movement(
            GameEvent(moved_entities=[EntityMovement(entity_id="MILA", to_scene_id="ANNEX")])
        )
        assert (host.state.current_scene_id, host.state.in_game_time) == before
        assert host.state.entity_states["MILA"]["current_scene_id"] == "ANNEX"

    monkeypatch.setattr(publication, "_apply", apply)
    return completed


def observed_frames(body):
    return [
        json.loads(row["text"]) for row in body["psychological_state"]["current_host_observations"]
    ]
