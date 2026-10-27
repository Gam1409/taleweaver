from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.orm.attributes import flag_modified

from backend.models.world_entity import WorldEntity


class ContainerInteractions:
    async def _resolve_container_target(
        self, hint: str
    ) -> tuple[WorldEntity | None, dict[str, Any] | None, int | None]:
        normalized_hint = (hint or "").strip().lower()
        if not normalized_hint:
            return None, None, None

        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id,
                WorldEntity.current_scene_id == self.state.current_scene_id,
                WorldEntity.entity_type == "OBJECT",
                or_(
                    WorldEntity.id == hint,
                    WorldEntity.name == hint,
                ),
            )
        )
        scene_ent = ent_res.scalars().first()
        if scene_ent and str(scene_ent.item_type or "").upper() == "CONTAINER":
            return scene_ent, None, None

        for idx, inv_item in enumerate(self.avatar.inventory or []):
            if not self._is_container_item(inv_item):
                continue
            item_id = str(inv_item.get("id") or "").strip().lower()
            item_name = str(inv_item.get("name") or "").strip().lower()
            if normalized_hint in {item_id, item_name}:
                return None, dict(inv_item), idx

        return None, None, None

    async def _get_container_inventory(
        self, scene_container: WorldEntity | None, inventory_container: dict[str, Any] | None
    ) -> list[Any]:
        if scene_container:
            states = dict(self.state.entity_states or {})
            state_inv = (states.get(scene_container.id) or {}).get("inventory")
            if isinstance(state_inv, list):
                return list(state_inv)
            return list(scene_container.inventory or [])

        if inventory_container:
            return list(inventory_container.get("inventory") or [])

        return []

    async def _normalize_container_item_ref(self, item_ref: Any) -> dict[str, Any] | None:
        if isinstance(item_ref, dict):
            return dict(item_ref)

        if isinstance(item_ref, str) and item_ref.strip():
            item_id = item_ref.strip()
            ent_res = await self.db.execute(
                select(WorldEntity).where(
                    WorldEntity.session_id == self.game_id,
                    WorldEntity.id == item_id,
                )
            )
            ent = ent_res.scalars().first()
            if ent:
                item_data = jsonable_encoder(
                    {c.name: getattr(ent, c.name) for c in ent.__table__.columns}
                )
                metadata = dict(ent.metadata_json or {})
                for key in [
                    "hp_change",
                    "mana_change",
                    "stamina_change",
                    "stat_modifier_strength",
                    "stat_modifier_dexterity",
                    "stat_modifier_intelligence",
                    "stat_modifier_wisdom",
                    "stat_modifier_charisma",
                    "stat_modifier_armor_class",
                ]:
                    if key not in item_data and key in metadata:
                        item_data[key] = metadata[key]
                return item_data

            return {"id": item_id, "name": item_id}

        return None

    async def _normalize_container_items(self, raw_items: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in raw_items or []:
            normalized_item = await self._normalize_container_item_ref(item)
            if normalized_item:
                normalized.append(normalized_item)
        return normalized

    async def _move_container_item_to_inventory(self, item: dict[str, Any]) -> None:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return

        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id,
                WorldEntity.id == item_id,
            )
        )
        ent = ent_res.scalars().first()
        if ent:
            ent.is_in_inventory = True
            ent.current_scene_id = "INVENTORY"
            ent.is_hidden = False

        states = dict(self.state.entity_states or {})
        if item_id not in states:
            states[item_id] = {}
        states[item_id]["is_in_inventory"] = True
        states[item_id]["current_scene_id"] = "INVENTORY"
        states[item_id]["is_hidden"] = False
        self.state.entity_states = states
        flag_modified(self.state, "entity_states")

    async def _move_container_item_to_scene(self, item: dict[str, Any]) -> bool:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return False

        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id,
                WorldEntity.id == item_id,
            )
        )
        ent = ent_res.scalars().first()
        if not ent:
            return False

        ent.is_in_inventory = False
        ent.current_scene_id = self.state.current_scene_id
        ent.is_hidden = False

        states = dict(self.state.entity_states or {})
        if item_id not in states:
            states[item_id] = {}
        states[item_id]["is_in_inventory"] = False
        states[item_id]["current_scene_id"] = self.state.current_scene_id
        states[item_id]["is_hidden"] = False
        self.state.entity_states = states
        flag_modified(self.state, "entity_states")
        return True

    async def _clear_container_inventory(
        self,
        scene_container: WorldEntity | None,
        inventory_container: dict[str, Any] | None,
        inventory_idx: int | None,
    ) -> None:
        await self._set_container_inventory(scene_container, inventory_container, inventory_idx, [])

    async def _take_single_container_item(self, args: str) -> str:
        """Handle `/container_take_item <container> | <item id or name>`."""
        container_hint, _, item_hint = (part.strip() for part in args.partition("|"))
        if not container_hint or not item_hint:
            return "Usage: /container_take_item <container> | <item>"

        scene_container, inventory_container, inventory_idx = await self._resolve_container_target(
            container_hint
        )
        source = scene_container or inventory_container
        if not source:
            return f"No container named '{container_hint}' was found."
        container_name = (
            scene_container.name if scene_container else inventory_container.get("name")
        )
        if self._is_container_locked(scene_container, inventory_container):
            return f"{container_name} is locked."

        raw_items = await self._get_container_inventory(scene_container, inventory_container)
        wanted = item_hint.lower()
        match_idx = None
        match_item: dict[str, Any] | None = None
        for idx, raw in enumerate(raw_items):
            normalized = await self._normalize_container_item_ref(raw)
            if not normalized:
                continue
            candidates = {str(normalized.get(k) or "").lower() for k in ("id", "name")}
            if wanted in candidates:
                match_idx, match_item = idx, normalized
                break
        if match_idx is None or match_item is None:
            return f"{container_name} does not contain '{item_hint}'."

        await self._move_container_item_to_inventory(match_item)
        self.avatar.inventory = [*(self.avatar.inventory or []), match_item]
        remaining = [raw for idx, raw in enumerate(raw_items) if idx != match_idx]
        await self._set_container_inventory(
            scene_container, inventory_container, inventory_idx, remaining
        )
        return f"You take {match_item.get('name') or item_hint} from {container_name}."

    async def _set_container_inventory(
        self,
        scene_container: WorldEntity | None,
        inventory_container: dict[str, Any] | None,
        inventory_idx: int | None,
        items: list[Any],
    ) -> None:
        if scene_container:
            scene_container.inventory = list(items)
            self.db.add(scene_container)

            states = dict(self.state.entity_states or {})
            if scene_container.id not in states:
                states[scene_container.id] = {}
            states[scene_container.id]["inventory"] = list(items)
            self.state.entity_states = states
            flag_modified(self.state, "entity_states")

        if inventory_container is not None and inventory_idx is not None:
            updated_inventory = list(self.avatar.inventory or [])
            if 0 <= inventory_idx < len(updated_inventory) and isinstance(
                updated_inventory[inventory_idx], dict
            ):
                updated_container = dict(updated_inventory[inventory_idx])
                updated_container["inventory"] = list(items)
                updated_inventory[inventory_idx] = updated_container
                self.avatar.inventory = updated_inventory
