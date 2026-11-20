"""Ground wardrobe proposals before the canonical mutation pipeline runs."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from backend.engine.clothing.actions import GarmentCreation, WardrobeAction
from backend.engine.clothing.context import actor_records, source_records
from backend.engine.clothing.plan_sources import PlanSources, capture
from backend.engine.clothing.profiles import load_profile
from backend.engine.npc_actions.prepass import defer_wardrobe
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot
from backend.models.chat import ChatMessage


@dataclass
class WardrobePlan:
    message_id: str
    scene_id: str
    actions: list[WardrobeAction] = field(default_factory=list)
    creations: list[GarmentCreation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sources: PlanSources | None = None
    rejected: list[WardrobeAction | GarmentCreation] = field(default_factory=list)
    requires_narration: bool = False
    narrated_gift_indices: set[int] = field(default_factory=set)


def _grounded(change: Any, actor: dict, user_msg: str, narration: str) -> bool:
    if not actor or change.basis != "performed":
        return False
    text = {
        "player_action": user_msg,
        "completed_narration": narration,
        "actor_description": actor["description"],
    }[change.source]
    if change.evidence not in text:
        return False
    if change.actor_id == PLAYER:
        return bool(change.agency != "npc_choice")
    if change.source == "player_action":
        return (
            change.agency in {"npc_choice", "consented_assistance"}
            and change.npc_decision == "approved"
        )
    return True


def _creation_source_valid(
    creation: GarmentCreation, actor: dict, sources: dict, possessions: Any, narration: str = ""
) -> bool:
    if creation.acquisition == "established_wear":
        return (
            creation.source == "actor_description"
            and creation.source_id == creation.actor_id
            and creation.wear
            and creation.source_evidence in actor.get("description", "")
            and load_profile(actor.get("visual_profile")) is None
            and not actor.get("visual_profile")
        )
    source = sources.get(creation.source_id, {})
    if (
        creation.source == "actor_description"
        or not source
        or not (
            creation.source_evidence in source.get("description", "")
            or (creation.acquisition == "gift" and creation.source_evidence in narration)
        )
    ):
        return False
    if creation.acquisition == "wardrobe":
        return source.get("kind") in {"container", "scene"}
    if creation.acquisition == "gift":
        return source.get("kind") == "npc" and creation.source_id != creation.actor_id
    if creation.acquisition == "shop":
        return source.get("kind") in {"npc", "scene"}
    return bool(creation.material_item_ids) and all(
        possessions.owners.get(item_id) == creation.actor_id
        for item_id in creation.material_item_ids
    )


def validate_plan(
    manager: Any,
    proposal: Any,
    user_msg: str,
    narration: str,
    entities: list[Any],
    scenes: list[Any],
    *,
    item_plan: Any = None,
) -> WardrobePlan:
    plan = WardrobePlan(
        str(getattr(manager, "_vn_player_message_id", "") or ""), manager.state.current_scene_id
    )
    actors = actor_records(manager, entities)
    sources = source_records(manager, entities, scenes)
    possessions = possession_snapshot(manager, entities)
    for change in getattr(proposal, "wardrobe_actions", None) or []:
        if defer_wardrobe(manager.state, change, item_plan=item_plan):
            continue
        valid = bool(plan.message_id) and _grounded(
            change, actors.get(change.actor_id, {}), user_msg, narration
        )
        if valid and change.source != "actor_description":
            plan.actions.append(change)
        else:
            plan.rejected.append(change)
            plan.errors.append(
                "A wardrobe change lacked completed action evidence or character agency."
            )
    for index, creation in enumerate(getattr(proposal, "garment_creations", None) or []):
        if defer_wardrobe(manager.state, creation, item_plan=item_plan, creation_ref=index):
            continue
        actor = actors.get(creation.actor_id, {})
        valid = bool(plan.message_id) and _grounded(creation, actor, user_msg, narration)
        valid = valid and _creation_source_valid(creation, actor, sources, possessions, narration)
        known = any(
            item.get("name", "").casefold() == creation.name.casefold()
            for item in possessions.items.values()
        )
        if valid and not known:
            plan.creations.append(creation)
            narrated_gift = (
                creation.acquisition == "gift"
                and creation.source_evidence
                not in sources.get(creation.source_id, {}).get("description", "")
            )
            plan.requires_narration |= narrated_gift
            # Use the accepted plan namespace; earlier rejected/deferred proposals
            # must not shift a gift onto another creation's authored-source proof.
            plan.narrated_gift_indices.update((len(plan.creations) - 1,) if narrated_gift else ())
        else:
            plan.rejected.append(creation)
            plan.errors.append(
                "A new garment lacked an available established source; no clothing was created."
            )
    return plan


async def prepare_wardrobe_plan(
    manager: Any, event: Any, proposal: Any, user_msg: str, entities: list[Any], scenes: list[Any]
) -> None:
    if not (
        getattr(proposal, "wardrobe_actions", None) or getattr(proposal, "garment_creations", None)
    ):
        return
    previous = await manager.db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.state.session_id,
            ChatMessage.role == "assistant",
            ChatMessage.is_debug.is_(False),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    narration = (
        str(previous.content or "")[-6000:]
        if previous and previous.scene_id == manager.state.current_scene_id
        else ""
    )
    plan = validate_plan(
        manager,
        proposal,
        user_msg,
        narration,
        entities,
        scenes,
        item_plan=getattr(event, "_vn_player_item_plan", None),
    )
    plan.sources = await capture(manager, user_msg, previous)
    event._vn_clothing_plan = plan
