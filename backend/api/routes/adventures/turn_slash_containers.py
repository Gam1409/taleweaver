from __future__ import annotations


async def open_container(self, command):
    container_hint = command.response.replace("[TRIGGER_OPEN]", "").strip()
    if not container_hint:
        command.response = "Usage: /open <container>"
    else:
        scene_container, inventory_container, _ = await self._resolve_container_target(
            container_hint
        )
        container_name = (
            (scene_container.name if scene_container else inventory_container.get("name"))
            if (scene_container or inventory_container)
            else None
        )
        if not container_name:
            command.response = f"No container named '{container_hint}' was found."
        else:
            is_locked = self._is_container_locked(scene_container, inventory_container)
            if is_locked:
                command.response = f"{container_name} is locked."
            else:
                container_inventory = await self._get_container_inventory(
                    scene_container, inventory_container
                )
                command.response = f"{container_name} contains {len(container_inventory)} item(s)."


async def take_all(self, command):
    container_hint = command.response.replace("[TRIGGER_CONTAINER_TAKE_ALL]", "").strip()
    if not container_hint:
        command.response = "Usage: /container_take_all <container>"
    else:
        (
            scene_container,
            inventory_container,
            inventory_idx,
        ) = await self._resolve_container_target(container_hint)
        container_name = (
            (scene_container.name if scene_container else inventory_container.get("name"))
            if (scene_container or inventory_container)
            else None
        )
        if not container_name:
            command.response = f"No container named '{container_hint}' was found."
        else:
            is_locked = self._is_container_locked(scene_container, inventory_container)
            if is_locked:
                command.response = f"{container_name} is locked."
            else:
                raw_items = await self._get_container_inventory(
                    scene_container, inventory_container
                )
                normalized_items = await self._normalize_container_items(raw_items)
                if not normalized_items:
                    command.response = f"{container_name} is empty."
                else:
                    new_inventory = list(self.avatar.inventory or [])
                    for item in normalized_items:
                        new_inventory.append(item)
                        await self._move_container_item_to_inventory(item)
                    self.avatar.inventory = new_inventory
                    await self._clear_container_inventory(
                        scene_container, inventory_container, inventory_idx
                    )
                    command.response = (
                        f"You take all {len(normalized_items)} item(s) from {container_name}."
                    )


async def drop_contents(self, command):
    container_hint = command.response.replace("[TRIGGER_CONTAINER_DROP_SCENE]", "").strip()
    if not container_hint:
        command.response = "Usage: /container_drop_scene <container>"
    else:
        (
            scene_container,
            inventory_container,
            inventory_idx,
        ) = await self._resolve_container_target(container_hint)
        container_name = (
            (scene_container.name if scene_container else inventory_container.get("name"))
            if (scene_container or inventory_container)
            else None
        )
        if not container_name:
            command.response = f"No container named '{container_hint}' was found."
        else:
            is_locked = self._is_container_locked(scene_container, inventory_container)
            if is_locked:
                command.response = f"{container_name} is locked."
            else:
                raw_items = await self._get_container_inventory(
                    scene_container, inventory_container
                )
                normalized_items = await self._normalize_container_items(raw_items)
                if not normalized_items:
                    command.response = f"{container_name} is empty."
                else:
                    for item in normalized_items:
                        moved = await self._move_container_item_to_scene(item)
                        if not moved:
                            await self._spawn_scene_item(item)
                    await self._clear_container_inventory(
                        scene_container, inventory_container, inventory_idx
                    )
                    command.response = f"You drop {len(normalized_items)} item(s) from {container_name} into the scene."
