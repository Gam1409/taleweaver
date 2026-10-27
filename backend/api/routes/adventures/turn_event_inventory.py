from __future__ import annotations

import logging
import re
from typing import Any

from backend.utils.path_security import ensure_within_data_dir as _ensure_within_data_dir
from backend.utils.path_security import sanitize_path_component as _sanitize_path_component

logger = logging.getLogger(__name__)


def _is_consumable(item: Any) -> bool:
    return str(getattr(item, "item_type", "") or "").upper() == "CONSUMABLE"


def _allocate_copied_item_id(source_id: str | None, existing_item_ids: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", source_id or "CONSUMABLE")[:40] or "CONSUMABLE"
    counter = 1
    candidate = f"{base}_COPY_{counter}"
    while candidate in existing_item_ids:
        counter += 1
        candidate = f"{base}_COPY_{counter}"
    return candidate


class TurnEventInventory:
    """Apply inventory outcomes in the turn transaction."""

    async def _prepare_inventory_items(self, event, vn_mode):
        existing_item_ids = await self._collect_existing_item_ids()

        # If we are removing items in this event, they don't count as "existing" for duplicate checks
        # if the LLM wants to replace them with an updated version using the same ID.
        if event.removed_inventory_item_ids:
            logger.info(
                "[Turn %s] Removing from duplicate check: %s",
                self.game_id,
                event.removed_inventory_item_ids,
            )
            existing_item_ids -= set(event.removed_inventory_item_ids)

        logger.info(
            "[Turn %s] Existing inventory IDs after removals: %s",
            self.game_id,
            list(existing_item_ids),
        )

        await self._prepare_new_inventory_items(event, vn_mode, existing_item_ids)

        await self._prepare_spawned_items(event, vn_mode, existing_item_ids)

    async def _prepare_new_inventory_items(self, event, vn_mode, existing_item_ids):
        if not (event.new_inventory_items):
            return
        filtered_inventory_items = []
        for item in event.new_inventory_items:
            match = (
                next(
                    (
                        i
                        for i in (self.avatar.inventory or [])
                        if isinstance(i, dict) and i.get("id") == item.id
                    ),
                    None,
                )
                if item.id
                else None
            )

            if item.id and item.id in existing_item_ids and _is_consumable(item) and not vn_mode:
                if not item.image_url and isinstance(match, dict) and match.get("image_url"):
                    item.image_url = match.get("image_url")
                source_id = item.id
                item.id = _allocate_copied_item_id(source_id, existing_item_ids)
                logger.info(
                    "[Turn %s] Cloning duplicate consumable %s as %s",
                    self.game_id,
                    source_id,
                    item.id,
                )

            await self._ensure_inventory_item_image(item)

            if item.id and item.id in existing_item_ids:
                # Check if it's a true duplicate (same name)
                if match:
                    if match.get("name") == item.name:
                        logger.info(
                            "[Turn %s] Skipping true duplicate inventory item id: %s",
                            self.game_id,
                            item.id,
                        )
                        continue
                    else:
                        logger.info(
                            "[Turn %s] Permitting implied update for item id %s (Name: %s -> %s)",
                            self.game_id,
                            item.id,
                            match.get("name"),
                            item.name,
                        )
                else:
                    logger.info(
                        "[Turn %s] Permitting pickup/implied update for item id %s (exists in session but not in inventory)",
                        self.game_id,
                        item.id,
                    )

            filtered_inventory_items.append(item)
            if item.id:
                existing_item_ids.add(item.id)
        event.new_inventory_items = filtered_inventory_items

    async def _prepare_spawned_items(self, event, vn_mode, existing_item_ids):
        if not (event.spawned_items):
            return
        filtered_spawned_items = []
        for item in event.spawned_items:
            match = (
                next(
                    (
                        i
                        for i in (self.avatar.inventory or [])
                        if isinstance(i, dict) and i.get("id") == item.id
                    ),
                    None,
                )
                if item.id
                else None
            )
            # Allow if it's a replacement for an item being removed
            is_replacement = (
                event.removed_inventory_item_ids and item.id in event.removed_inventory_item_ids
            )
            if (
                item.id
                and item.id in existing_item_ids
                and not is_replacement
                and _is_consumable(item)
                and not vn_mode
            ):
                if not item.image_url and isinstance(match, dict) and match.get("image_url"):
                    item.image_url = match.get("image_url")
                source_id = item.id
                item.id = _allocate_copied_item_id(source_id, existing_item_ids)
                logger.info(
                    "[Turn %s] Cloning duplicate spawned consumable %s as %s",
                    self.game_id,
                    source_id,
                    item.id,
                )

            if (
                item.id
                and item.id in existing_item_ids
                and not is_replacement
                and match
                and match.get("name") == item.name
            ):
                logger.info(
                    "[Turn %s] Skipping true duplicate spawned item id: %s",
                    self.game_id,
                    item.id,
                )
                continue

            filtered_spawned_items.append(item)
            if item.id:
                existing_item_ids.add(item.id)
        event.spawned_items = filtered_spawned_items

    async def _ensure_inventory_item_image(self, item):
        if not item.image_url:
            try:
                import os
                import uuid

                from backend.core.config import settings
                from backend.engine.media_engine import MediaEngine

                item_type = item.item_type or "PICKABLE"
                safe_id = re.sub(
                    r"[^A-Za-z0-9_\-]", "_", item.id or f"LOOT_{uuid.uuid4().hex[:8]}"
                )[:50]
                safe_adventure_id = _sanitize_path_component(self.adventure.id) or "adventure"
                target_dir = _ensure_within_data_dir(
                    os.path.join(
                        settings.DATA_DIR,
                        "adventures",
                        "library",
                        safe_adventure_id,
                        "entities",
                    )
                )
                item.image_url = await MediaEngine.generate_placeholder(
                    adventure_id=self.adventure.id,
                    entity_id=safe_id,
                    target_dir=target_dir,
                    category=f"ITEM_{item_type.upper()}",
                )
            except Exception as e:
                logger.error("Failed to generate new inventory item placeholder: %s", e)
