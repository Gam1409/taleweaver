from __future__ import annotations

import logging

from sqlalchemy import and_, func, or_, select

from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


class TurnEventInventoryHooks:
    """Apply inventory hooks outcomes in the turn transaction."""

    async def _apply_inventory_hooks(self, event, states, system_messages):
        state_dirty = False
        state_dirty = await self._apply_pickup_hooks(event, states, system_messages)

        await self._apply_drop_hooks(event, system_messages)

        return state_dirty

    async def _apply_pickup_hooks(self, event, states, system_messages):
        state_dirty = False
        if not (event.new_inventory_items):
            return False
        for item in event.new_inventory_items:
            if item.id:
                if item.id not in states:
                    states[item.id] = {}
                states[item.id]["is_in_inventory"] = True
                state_dirty = True

                item_id_str = item.id.strip() if item.id else ""
                item_name_str = (item.name or "").strip()
                name_clauses = [func.upper(WorldEntity.name) == item_id_str.upper()]
                if item_name_str:
                    name_clauses.append(func.upper(WorldEntity.name) == item_name_str.upper())

                ent_res = await self.db.execute(
                    select(WorldEntity)
                    .where(
                        or_(func.upper(WorldEntity.id) == item_id_str.upper(), *name_clauses),
                        or_(
                            WorldEntity.session_id == self.game_id,
                            and_(
                                WorldEntity.template_id == self.adventure.id,
                                WorldEntity.session_id.is_(None),
                            ),
                        ),
                    )
                    .order_by(WorldEntity.session_id.desc().nulls_last())
                )
                ent_obj = ent_res.scalars().first()
                await self._fire_pickup_hook(ent_obj, system_messages)

        return state_dirty

    async def _apply_drop_hooks(self, event, system_messages):
        if not (event.removed_inventory_item_ids):
            return
        for item_id in event.removed_inventory_item_ids:
            if item_id:
                item_id_str = item_id.strip()
                ent_res = await self.db.execute(
                    select(WorldEntity)
                    .where(
                        or_(
                            func.upper(WorldEntity.id) == item_id_str.upper(),
                            func.upper(WorldEntity.name) == item_id_str.upper(),
                        ),
                        or_(
                            WorldEntity.session_id == self.game_id,
                            and_(
                                WorldEntity.template_id == self.adventure.id,
                                WorldEntity.session_id.is_(None),
                            ),
                        ),
                    )
                    .order_by(WorldEntity.session_id.desc().nulls_last())
                )
                ent_obj = ent_res.scalars().first()
                await self._fire_drop_hook(ent_obj, item_id, system_messages)

    async def _fire_pickup_hook(self, ent_obj, system_messages):
        if not (ent_obj):
            return
        meta = dict(ent_obj.metadata_json or {})
        if (
            not meta.get("on_pickup_script")
            and not meta.get("on_pickup_text")
            and hasattr(self, "adventure")
            and self.adventure
        ):
            tpl_res = await self.db.execute(
                select(WorldEntity).where(
                    or_(
                        func.upper(WorldEntity.id) == ent_obj.id.upper(),
                        func.upper(WorldEntity.name) == ent_obj.name.upper(),
                    ),
                    WorldEntity.template_id == self.adventure.id,
                    WorldEntity.session_id.is_(None),
                )
            )
            tpl_ent = tpl_res.scalars().first()
            if tpl_ent and tpl_ent.metadata_json:
                for k, v in tpl_ent.metadata_json.items():
                    if k not in meta:
                        meta[k] = v
        if meta.get("on_pickup_script"):
            msgs = await self.manager._execute_inline_script(
                meta["on_pickup_script"], "on_pickup", ent_obj.id
            )
            system_messages.extend(msgs)
        if meta.get("on_pickup_text"):
            await self._save_chat_message("system", meta["on_pickup_text"])
            system_messages.append(meta["on_pickup_text"])

    async def _fire_drop_hook(self, ent_obj, item_id, system_messages):
        if not (ent_obj):
            return
        meta = dict(ent_obj.metadata_json or {})
        if (
            not meta.get("on_drop_script")
            and not meta.get("on_drop_text")
            and hasattr(self, "adventure")
            and self.adventure
        ):
            tpl_res = await self.db.execute(
                select(WorldEntity).where(
                    func.upper(WorldEntity.id) == item_id.strip().upper(),
                    WorldEntity.template_id == self.adventure.id,
                    WorldEntity.session_id.is_(None),
                )
            )
            tpl_ent = tpl_res.scalars().first()
            if tpl_ent and tpl_ent.metadata_json:
                for k, v in tpl_ent.metadata_json.items():
                    if k not in meta:
                        meta[k] = v
        if meta.get("on_drop_script"):
            msgs = await self.manager._execute_inline_script(
                meta["on_drop_script"], "on_drop", item_id
            )
            system_messages.extend(msgs)
        if meta.get("on_drop_text"):
            await self._save_chat_message("system", meta["on_drop_text"])
            system_messages.append(meta["on_drop_text"])
