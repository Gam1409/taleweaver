from __future__ import annotations

import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from backend.models.world_entity import WorldEntity


async def take_direct(self, command):
    entity_id_or_name = command.response[21:].strip()
    take_npc = await self._find_scene_npc_by_hint(entity_id_or_name)
    if take_npc and self._is_npc_defeated(take_npc):
        msg = f"{take_npc.name} is defeated. Only inspect is available."
        yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': msg})}\n\n"
        async for chunk in self._emit_combat_final(msg):
            yield chunk
        command.halted = True
        return

    ent = await _pickup_target(self, entity_id_or_name)

    already_in_inv = bool(
        ent
        and any(
            (isinstance(i, dict) and str(i.get("id") or "").lower() == ent.id.lower())
            or (isinstance(i, str) and i.lower() == ent.id.lower())
            for i in (self.avatar.inventory or [])
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
    elif ent and ent.is_portable and str(ent.item_type or "").upper() != "SWITCH":
        command.response = await _acquire_pickup(self, ent)

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
    else:
        command.response = "You cannot take that."


async def _pickup_target(self, entity_id_or_name):
    # Find portable OBJECT in current scene (snapshot), matching by name or ID (case-insensitive).
    ent_res = await self.db.execute(
        select(WorldEntity).where(
            WorldEntity.session_id == self.game_id,
            WorldEntity.current_scene_id == self.state.current_scene_id,
            WorldEntity.entity_type == "OBJECT",
            WorldEntity.is_hidden.is_(False),
            WorldEntity.is_in_inventory.is_(False),
        )
    )
    candidates = ent_res.scalars().all()
    if not candidates:
        adv_id = (
            getattr(self.manager.adventure, "id", None)
            if hasattr(self.manager, "adventure") and self.manager.adventure
            else (
                getattr(self.avatar, "template_id", None)
                or getattr(self.state, "template_id", None)
            )
        )
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
            candidates = tpl_res.scalars().all()
    hint_lower = entity_id_or_name.lower()
    ent = None
    overrides = self.state.entity_states or {}
    for candidate in candidates:
        cand_ov = overrides.get(candidate.id, {})
        if cand_ov.get("is_in_inventory") or cand_ov.get("is_hidden"):
            continue
        if candidate.id and candidate.id.lower() == hint_lower:
            ent = candidate
            break
        if candidate.name and candidate.name.lower() == hint_lower:
            ent = candidate
            break

    return ent


async def _pickup_metadata(self, ent):
    pickup_meta = dict(ent.metadata_json or {}) if isinstance(ent.metadata_json, dict) else {}
    adv_id = (
        getattr(self.manager.adventure, "id", None)
        if hasattr(self.manager, "adventure") and self.manager.adventure
        else (getattr(self.avatar, "template_id", None) or getattr(self.state, "template_id", None))
    )
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


async def _acquire_pickup(self, ent):
    # Move to inventory
    new_inv = list(self.avatar.inventory or [])
    item_dict = jsonable_encoder({c.name: getattr(ent, c.name) for c in ent.__table__.columns})
    item_dict["is_in_inventory"] = True
    item_dict["current_scene_id"] = "INVENTORY"
    new_inv.append(item_dict)
    self.avatar.inventory = new_inv

    # Update DB entity directly
    ent.is_in_inventory = True
    ent.current_scene_id = "INVENTORY"

    # Update session state instead of global entity
    states = dict(self.state.entity_states or {})
    if ent.id not in states:
        states[ent.id] = {}
    states[ent.id]["is_in_inventory"] = True
    states[ent.id]["current_scene_id"] = "INVENTORY"
    self.state.entity_states = states
    flag_modified(self.state, "entity_states")
    response = f"Added {ent.name} to your inventory."
    await self._check_special_action_unlocks("FIND_ITEM", ent.id)

    return response
