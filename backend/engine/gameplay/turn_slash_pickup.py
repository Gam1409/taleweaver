from __future__ import annotations

from collections.abc import AsyncGenerator
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.engine.gameplay.turn_slash import SlashCommandState, SlashInteractions

import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from backend.engine.visual_novel.continuity import PLAYER, SCENE, Possessions, possession_snapshot
from backend.models.world_entity import WorldEntity


async def take_direct(
    self: SlashInteractions, command: SlashCommandState
) -> AsyncGenerator[str, None]:
    entity_id_or_name = command.response[21:].strip()
    take_npc = await self._find_scene_npc_by_hint(entity_id_or_name)
    if take_npc and self._is_npc_defeated(take_npc):
        msg = f"{take_npc.name} is defeated. Only inspect is available."
        yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': msg})}\n\n"
        async for chunk in self._emit_combat_final(msg):
            yield chunk
        command.halted = True
        return

    target = await _pickup_target(self, entity_id_or_name)
    if target is None:
        command.response = "You cannot take that."
        return
    ent, canonical = target
    ent = _session_item(self, ent)

    already_in_inv = bool(
        ent
        and any(
            (isinstance(i, dict) and str(i.get("id") or "").lower() == ent.id.lower())
            or (isinstance(i, str) and i.lower() == ent.id.lower())
            for i in cast(list[dict[str, Any] | str], self.avatar.inventory or [])
        )
    )

    if ent and already_in_inv:
        ent.is_in_inventory = True
        ent.current_scene_id = "INVENTORY"
        states = dict(self.state.entity_states or {})
        states.setdefault(ent.id, {})["is_in_inventory"] = True
        states[ent.id]["current_scene_id"] = "INVENTORY"
        self.state.entity_states = states
        flag_modified(self.state, "entity_states")
        command.response = f"{ent.name} is already in your inventory."
    else:
        command.response = await _acquire_pickup(self, ent, canonical)

        pickup_meta = await _pickup_metadata(self, ent)

        if pickup_meta.get("on_pickup_script"):
            script_msgs = await self.manager._execute_inline_script(
                pickup_meta["on_pickup_script"], "on_pickup", ent.id
            )
            for sm in script_msgs:
                role = getattr(sm, "role", "system")
                yield f"event: {role}\ndata: {json.dumps({'role': role, 'content': str(sm)})}\n\n"
        if pickup_meta.get("on_pickup_text"):
            await self._save_chat_message("system", pickup_meta["on_pickup_text"])
            yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': pickup_meta['on_pickup_text']})}\n\n"

        pickup_cfg = pickup_meta.get("pickup_trigger")
        if isinstance(pickup_cfg, dict):
            pickup_mode = str(pickup_cfg.get("mode") or "silent").strip().lower()
            if pickup_mode in {"narration", "turn"}:
                self.pending_pickup_trigger = {
                    "mode": pickup_mode,
                    "cue": str(pickup_cfg.get("cue") or "").strip(),
                    "item_name": ent.name,
                    "item_id": ent.id,
                }


async def _pickup_target(
    self: SlashInteractions, entity_id_or_name: str
) -> tuple[WorldEntity, dict[str, Any]] | None:
    # The same possession projection governs model transfers and direct pickup.
    rows = list(
        await self.db.scalars(select(WorldEntity).where(WorldEntity.session_id == self.game_id))
    )
    snapshot = possession_snapshot(self.manager, rows)
    target = _match_pickup(rows, snapshot, entity_id_or_name)
    if target is not None or SCENE in snapshot.owners.values():
        return target
    # Legacy sessions may lack a materialized template item. Existing session IDs
    # still shadow template rows, including unavailable possessions and moved items.
    templates = []
    adv_id = _template_id(self)
    if adv_id:
        tpl_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.template_id == adv_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.current_scene_id == self.state.current_scene_id,
                WorldEntity.entity_type == "OBJECT",
                WorldEntity.is_hidden.is_(False),
                WorldEntity.is_in_inventory.is_(False),
            )
        )
        existing = {row.id for row in rows}
        templates = [row for row in tpl_res.scalars().all() if row.id not in existing]
    rows.extend(templates)
    return _match_pickup(rows, possession_snapshot(self.manager, rows), entity_id_or_name)


def _match_pickup(
    rows: list[WorldEntity], snapshot: Possessions, hint: str
) -> tuple[WorldEntity, dict[str, Any]] | None:
    hint = hint.casefold()
    for row in rows:
        item = snapshot.items.get(row.id)
        owner = snapshot.owners.get(row.id)
        if row.entity_type != "OBJECT" or item is None or owner not in {SCENE, PLAYER}:
            continue
        if owner == SCENE and str(item.get("item_type") or row.item_type).upper() == "SWITCH":
            continue
        if hint in {row.id.casefold(), str(item.get("name") or "").casefold()}:
            return row, item
    return None


def _template_id(self: SlashInteractions) -> str | None:
    return (
        getattr(self.manager.adventure, "id", None)
        if self.manager.adventure
        else (self.avatar.template_id or self.state.template_id)
    )


def _session_item(self: SlashInteractions, entity: WorldEntity) -> WorldEntity:
    if entity.session_id == self.game_id:
        return entity
    # A compatibility pickup must not mutate the shared adventure template.
    data = {
        column.name: deepcopy(getattr(entity, column.name))
        for column in entity.__table__.columns
        if column.computed is None
        and not column.primary_key
        and column.name not in {"template_id", "session_id", "created_at", "updated_at"}
    }
    result = WorldEntity(**data, session_id=self.game_id)
    self.db.add(result)
    return result


async def _pickup_metadata(self: SlashInteractions, ent: WorldEntity) -> dict[str, Any]:
    pickup_meta = dict(ent.metadata_json or {}) if isinstance(ent.metadata_json, dict) else {}
    adv_id = _template_id(self)
    if adv_id and (
        not pickup_meta.get("on_pickup_script") and not pickup_meta.get("on_pickup_text")
    ):
        tpl_res = await self.db.execute(
            select(WorldEntity).where(
                func.upper(WorldEntity.id) == ent.id.upper(),
                WorldEntity.template_id == adv_id,
                WorldEntity.session_id.is_(None),
            )
        )
        tpl_ent = tpl_res.scalars().first()
        if tpl_ent and tpl_ent.metadata_json:
            for k, v in tpl_ent.metadata_json.items():
                if k not in pickup_meta:
                    pickup_meta[k] = v

    return pickup_meta


async def _acquire_pickup(self: SlashInteractions, ent: WorldEntity, canonical: dict) -> str:
    # Move to inventory
    new_inv = list(self.avatar.inventory or [])
    item_dict = {
        **jsonable_encoder({c.name: getattr(ent, c.name) for c in ent.__table__.columns}),
        **deepcopy(canonical),
    }
    item_dict["is_in_inventory"] = True
    item_dict["current_scene_id"] = "INVENTORY"
    item_dict["spatial_position"] = None
    new_inv.append(item_dict)
    self.avatar.inventory = new_inv

    # Update DB entity directly
    ent.is_in_inventory = True
    ent.current_scene_id = "INVENTORY"
    ent.spatial_position = None

    # Update session state instead of global entity
    states = dict(self.state.entity_states or {})
    if ent.id not in states:
        states[ent.id] = {}
    states[ent.id]["is_in_inventory"] = True
    states[ent.id]["current_scene_id"] = "INVENTORY"
    states[ent.id]["spatial_position"] = None
    states[ent.id]["vn_item_data"] = deepcopy(item_dict)
    self.state.entity_states = states
    flag_modified(self.state, "entity_states")
    response = f"Added {ent.name} to your inventory."
    await self._check_special_action_unlocks("FIND_ITEM", ent.id)

    return response
