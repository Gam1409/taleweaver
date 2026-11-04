"""Bind confirmed co-arrivals to the server-assigned destination before movement guards."""

from typing import Any

from sqlalchemy import select

from backend.engine.dynamic_locations.schema import registry, save_registry
from backend.engine.npc_presence import physically_present
from backend.engine.rule_engine import EntityMovement
from backend.models.world_entity import WorldEntity


async def present_companions(manager: Any) -> list[dict]:
    rows = await manager.db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == manager.game_id,
            WorldEntity.entity_type == "NPC",
        )
    )
    result = []
    for npc in rows:
        override = (manager.state.entity_states or {}).get(npc.id) or {}
        if (
            override.get("current_scene_id", npc.current_scene_id) != manager.state.current_scene_id
            or override.get("is_hidden", npc.is_hidden)
            or override.get("is_defeated", False)
            or not physically_present(npc, manager.state)
        ):
            continue
        result.append(
            {
                "npc_id": npc.id,
                "name": override.get("name", npc.name),
                "character": npc.character,
                "goal": npc.goal,
                "moveable": override.get(
                    "moveable", npc.moveable or npc.movement_type == "MOVABLE"
                ),
            }
        )
    return result


def bind_companions(
    intent: Any, decision: Any, destination: str | None, context: dict, user_msg: str
) -> None:
    if not destination:
        return
    present = {npc["npc_id"] for npc in context.get("present_npcs", [])}
    confirmed = {
        companion.npc_id
        for companion in decision.companions
        if companion.npc_id in present and companion.evidence in user_msg
    }
    if not confirmed:
        return
    existing = [move for move in intent.moved_entities or [] if move.entity_id not in confirmed]
    intent.moved_entities = [
        *existing,
        *[
            EntityMovement(entity_id=identifier, to_scene_id=destination)
            for identifier in sorted(confirmed)
        ],
    ]


def record_arrival(
    manager: Any, decision: Any, destination: str | None, context: dict, user_msg: str
) -> None:
    if not destination:
        return
    names = {row["npc_id"]: row["name"] for row in context.get("present_npcs", [])}
    checks = [
        {
            "npc_id": row.npc_id,
            "name": names.get(row.npc_id, row.npc_id),
            "evidence": row.evidence,
            "status": "pending" if row.npc_id in names and row.evidence in user_msg else "rejected",
        }
        for row in decision.companions
    ]
    save_registry(
        manager.state,
        {
            **registry(manager.state),
            "last_arrival": {
                "destination": destination,
                "message_id": getattr(manager, "_vn_player_message_id", ""),
                "player_entered": False,
                "companions": checks,
            },
        },
    )


def finish_arrival(manager: Any) -> None:
    data = registry(manager.state)
    arrival = data.get("last_arrival")
    if not isinstance(arrival, dict) or arrival.get("finalized"):
        return
    entered = manager.state.current_scene_id == arrival["destination"]
    checks = []
    for companion in arrival.get("companions", []):
        result = dict(companion)
        if result["status"] == "pending":
            actual = (manager.state.entity_states or {}).get(result["npc_id"], {})
            result["status"] = (
                "moved"
                if entered and actual.get("current_scene_id") == arrival["destination"]
                else "not_moved"
            )
        checks.append(result)
    save_registry(
        manager.state,
        {
            **data,
            "last_arrival": {
                **arrival,
                "finalized": True,
                "player_entered": entered,
                "companions": checks,
            },
        },
    )
