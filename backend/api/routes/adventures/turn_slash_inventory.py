from __future__ import annotations

import json

from sqlalchemy import and_, func, or_, select

from backend.models.world_entity import WorldEntity


async def drop_item(self, command):
    item_name = command.response[14:].strip()
    if not item_name:
        command.response = "Usage: /drop <item name>"
    else:
        # Find item in inventory
        item_idx = -1
        for idx, item in enumerate(self.avatar.inventory or []):
            if isinstance(item, dict) and item.get("name", "").lower() == item_name.lower():
                item_idx = idx
                break

        if item_idx == -1:
            command.response = f"You don't have '{item_name}' in your inventory."
        else:
            new_inventory = list(self.avatar.inventory)
            dropped_item = new_inventory.pop(item_idx)
            self.avatar.inventory = new_inventory

            # Spawn in scene
            await self._spawn_scene_item(dropped_item)
            command.response = f"You dropped {dropped_item.get('name')}."

            drop_meta, dropped_id = await _drop_metadata(self, dropped_item)

            if drop_meta.get("on_drop_script") and dropped_id:
                script_msgs = await self.manager._execute_inline_script(
                    drop_meta["on_drop_script"], "on_drop", str(dropped_id)
                )
                for sm in script_msgs:
                    role = getattr(sm, "role", "system")
                    yield f"event: {role}\ndata: {json.dumps({'role': role, 'content': str(sm)})}\n\n"
            if drop_meta.get("on_drop_text"):
                await self._save_chat_message("system", drop_meta["on_drop_text"])
                yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': drop_meta['on_drop_text']})}\n\n"


async def equip_item(self, command):
    parts = command.response.replace("[TRIGGER_EQUIP]", "").strip().split("|", 1)
    item_id = parts[0].strip() if len(parts) > 0 else ""
    msg = parts[1].strip() if len(parts) > 1 else command.response

    if item_id and item_id != "None":
        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.id == item_id, WorldEntity.session_id == self.state.session_id
            )
        )
        ent_obj = ent_res.scalars().first()
        if ent_obj:
            meta = dict(ent_obj.metadata_json or {})
            if meta.get("on_equip_script"):
                msgs = await self.manager._execute_inline_script(
                    meta["on_equip_script"], "on_equip", item_id
                )
                for m in msgs:
                    role = getattr(m, "role", "system")
                    yield f"event: {role}\ndata: {json.dumps({'role': role, 'content': str(m)})}\n\n"
            if meta.get("on_equip_text"):
                await self._save_chat_message("system", meta["on_equip_text"])
                yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': meta['on_equip_text']})}\n\n"
    command.response = msg


async def unequip_item(self, command):
    parts = command.response.replace("[TRIGGER_UNEQUIP]", "").strip().split("|", 1)
    item_id = parts[0].strip() if len(parts) > 0 else ""
    msg = parts[1].strip() if len(parts) > 1 else command.response

    if item_id and item_id != "None":
        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.id == item_id, WorldEntity.session_id == self.state.session_id
            )
        )
        ent_obj = ent_res.scalars().first()
        if ent_obj:
            meta = dict(ent_obj.metadata_json or {})
            if meta.get("on_unequip_script"):
                msgs = await self.manager._execute_inline_script(
                    meta["on_unequip_script"], "on_unequip", item_id
                )
                for m in msgs:
                    role = getattr(m, "role", "system")
                    yield f"event: {role}\ndata: {json.dumps({'role': role, 'content': str(m)})}\n\n"
            if meta.get("on_unequip_text"):
                await self._save_chat_message("system", meta["on_unequip_text"])
                yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': meta['on_unequip_text']})}\n\n"
    command.response = msg


async def consume_item(self, command):
    item_name = command.response.replace("[TRIGGER_CONSUME]", "").strip()
    action_msg = self._consume_item_now(item_name)
    await self._save_chat_message("system", action_msg)
    yield f"event: system\ndata: {json.dumps({'role': 'system', 'content': action_msg})}\n\n"
    command.response = action_msg  # Allow it to fall through to persist and yield final state


async def _drop_metadata(self, dropped_item):
    drop_meta = dict(dropped_item.get("metadata_json") or {})
    dropped_id = dropped_item.get("id")
    adv_id = (
        getattr(self.manager.adventure, "id", None)
        if hasattr(self.manager, "adventure") and self.manager.adventure
        else (getattr(self.avatar, "template_id", None) or getattr(self.state, "template_id", None))
    )
    if (
        dropped_id
        and adv_id
        and (not drop_meta.get("on_drop_script") and not drop_meta.get("on_drop_text"))
    ):
        ent_res = await self.db.execute(
            select(WorldEntity)
            .where(
                func.upper(WorldEntity.id) == str(dropped_id).strip().upper(),
                or_(
                    WorldEntity.session_id == self.game_id,
                    and_(
                        WorldEntity.template_id == adv_id,
                        WorldEntity.session_id.is_(None),
                    ),
                ),
            )
            .order_by(WorldEntity.session_id.desc().nulls_last())
        )
        db_ent = ent_res.scalars().first()
        if db_ent and db_ent.metadata_json:
            for k, v in db_ent.metadata_json.items():
                if k not in drop_meta:
                    drop_meta[k] = v

    return drop_meta, dropped_id
