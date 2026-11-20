"""CONSTRUCTABLE items: deterministic crafting and blocking of illegal spawns/reveals.

A CONSTRUCTABLE is a hidden object that materializes when the player combines ALL of its
``combination_ingredients`` (minimum 2). Crafting requires the GM's ``combination_intent``
(set by the LLM in any language), reachable ingredients and an unambiguous result.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from backend.engine.gameplay.guardrails.base import (
    GuardrailBase,
    GuardrailNotice,
    entity_view,
    item_id_upper,
)
from backend.engine.rule_engine import GameEvent, InventoryItem
from backend.engine.switch_service import SwitchService
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)

MIN_INGREDIENTS = 2


@dataclass
class CraftingState:
    """Per-turn crafting bookkeeping."""

    entities_by_id: dict[str, WorldEntity]
    inventory_ids: dict[str, str]  # upper id -> original id (for removal)
    accessible_ids: set[str]
    constructed: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)


def _ingredients(ent: WorldEntity) -> set[str]:
    return {
        str(i).strip().upper() for i in ent.combination_ingredients or [] if i and str(i).strip()
    }


def _granted_by_gm(event: GameEvent, entity_id: str) -> bool:
    items = [*(event.new_inventory_items or []), *(event.spawned_items or [])]
    return any(item_id_upper(item) == entity_id.upper() for item in items)


def _legacy_ingredients(text: str, cs: CraftingState) -> set[str]:
    """Resolve old flag-only responses using whole, unambiguous inventory/catalog tokens."""
    aliases: dict[str, set[str]] = {}
    for identifier in cs.accessible_ids:
        ent = cs.entities_by_id.get(identifier)
        for token in (identifier, ent.name if ent else None):
            if token:
                aliases.setdefault(token.casefold(), set()).add(identifier)
    mentioned = set()
    folded = text.casefold()
    for alias, identifiers in aliases.items():
        if len(identifiers) == 1 and re.search(
            r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", folded
        ):
            mentioned.update(identifiers)
    return mentioned


class CraftingGuardMixin(GuardrailBase):
    """Resolves crafting and reverts constructables the GM produced without crafting."""

    def _crafting_state(self, entities: list[WorldEntity]) -> CraftingState:
        inventory_ids = {
            str(i["id"]).strip().upper(): str(i["id"])
            for i in self.avatar.inventory or []
            if isinstance(i, dict) and i.get("id")
        }
        scene_ids = set()
        for ent in entities:
            view = entity_view(ent, self.state.entity_states or {})
            if (
                ent.id
                and view.scene_id == self.state.current_scene_id
                and not view.in_inventory
                and not view.hidden
            ):
                scene_ids.add(ent.id.upper())
        return CraftingState(
            entities_by_id={e.id.upper(): e for e in entities if e.id},
            inventory_ids=inventory_ids,
            accessible_ids=set(inventory_ids) | scene_ids,
        )

    def _is_hidden_now(self, ent: WorldEntity) -> bool:
        override = (self.state.entity_states or {}).get(ent.id, {})
        if override.get("is_hidden") is not None:
            return bool(override["is_hidden"])
        return bool(ent.is_hidden)

    def _is_craftable(self, ent: WorldEntity, needed: set[str], cs: CraftingState) -> bool:
        return (
            len(needed) >= MIN_INGREDIENTS
            and self._is_hidden_now(ent)
            and needed.issubset(cs.accessible_ids)
        )

    async def _craft_guard_blocks(self, ent: WorldEntity) -> list[str] | None:
        """Runs the craft guard expression; returns failure messages or None when allowed."""
        meta = dict(ent.metadata_json or {})
        expression = str(meta.get("craft_guard_expression") or "").strip()
        if not expression:
            return None
        passed, detail = SwitchService.evaluate_gate_expression(
            expression, await self.manager._build_script_context()
        )
        if passed:
            return None
        messages = []
        if meta.get("on_craft_failure_script"):
            messages += await self.manager._execute_inline_script(
                meta["on_craft_failure_script"], "on_craft_failure", ent.id
            )
        fail_text = str(
            meta.get("on_craft_failure_text")
            or detail
            or f"You cannot construct {ent.name} right now."
        )
        return [*(GuardrailNotice(message) for message in messages), fail_text]

    def _consume_ingredients(self, event: GameEvent, needed: set[str], cs: CraftingState) -> bool:
        """Removes inventory ingredients / hides scene ingredients. True if all came from the inventory."""
        all_in_inventory = True
        for ingredient in sorted(needed):
            if ingredient in cs.inventory_ids:
                event.removed_inventory_item_ids = event.removed_inventory_item_ids or []
                original = cs.inventory_ids[ingredient]
                if original not in event.removed_inventory_item_ids:
                    event.removed_inventory_item_ids.append(original)
            else:
                self._upsert_entity_update(event, cs.entities_by_id[ingredient].id, is_hidden=True)
                all_in_inventory = False
        return all_in_inventory

    async def _craft(
        self, event: GameEvent, ent: WorldEntity, needed: set[str], cs: CraftingState
    ) -> None:
        all_in_inventory = self._consume_ingredients(event, needed, cs)
        self._upsert_entity_update(event, ent.id, is_hidden=False)
        self._upsert_entity_movement(event, ent.id, self.state.current_scene_id)
        if all_in_inventory:
            event.new_inventory_items = event.new_inventory_items or []
            if not any(i.id == ent.id for i in event.new_inventory_items):
                event.new_inventory_items.append(
                    InventoryItem(
                        id=ent.id,
                        name=ent.name or "Unknown Item",
                        description=ent.description,
                        item_type=ent.item_type,
                    )
                )
        cs.constructed.add(ent.id.upper())

        names = [
            cs.entities_by_id[i].name if i in cs.entities_by_id and cs.entities_by_id[i].name else i
            for i in sorted(needed)
        ]
        cs.messages.append(GuardrailNotice(f"You combine {', '.join(names)} to create {ent.name}!"))
        meta = dict(ent.metadata_json or {})
        if meta.get("on_craft_success_script"):
            messages = await self.manager._execute_inline_script(
                meta["on_craft_success_script"], "on_craft_success", ent.id
            )
            cs.messages.extend(GuardrailNotice(message) for message in messages)
        if meta.get("on_craft_success_text"):
            cs.messages.append(GuardrailNotice(meta["on_craft_success_text"]))
        logger.info(
            "[Turn %s] CONSTRUCTABLE '%s' materialized from ingredients %s",
            self.game_id,
            ent.id,
            sorted(needed),
        )

    @staticmethod
    def _discard_proposed_consumption(event: GameEvent, ingredients: set[str]) -> None:
        # The recipe owner consumes these IDs only after selection and validation.
        # Keep unrelated changes proposed in the same turn.
        if event.removed_inventory_item_ids:
            event.removed_inventory_item_ids = [
                identifier
                for identifier in event.removed_inventory_item_ids
                if identifier.upper() not in ingredients
            ]
        if event.deleted_entities:
            event.deleted_entities = [
                identifier
                for identifier in event.deleted_entities
                if identifier.upper() not in ingredients
            ]
        for change in list(event.updated_entities or []):
            if change.entity_id.upper() in ingredients and change.is_hidden is True:
                change.is_hidden = None
                if (
                    not change.model_dump(exclude={"entity_id"}, exclude_none=True)
                    and event.updated_entities
                ):
                    event.updated_entities.remove(change)

    @staticmethod
    def _recipe_candidates(
        event: GameEvent, constructables: list[WorldEntity], cs: CraftingState, user_msg: str
    ) -> tuple[list[WorldEntity], set[str]]:
        selected = (event.combination_result_id or "").strip().upper()
        ingredients = {value.strip().upper() for value in event.combination_ingredient_ids or []}
        grants = [ent for ent in constructables if _granted_by_gm(event, ent.id)]
        if selected:
            candidates = [ent for ent in constructables if ent.id.upper() == selected]
        elif grants:
            candidates = grants
        else:
            ingredients = ingredients or _legacy_ingredients(user_msg, cs)
            candidates = constructables if ingredients else []
        protected = set(ingredients)
        if selected or grants:
            for recipe in candidates:
                protected.update(_ingredients(recipe))
        if ingredients:
            candidates = [ent for ent in candidates if _ingredients(ent) == ingredients]
        return candidates, protected

    async def _try_craft(
        self, event: GameEvent, constructables: list[WorldEntity], cs: CraftingState, user_msg: str
    ) -> None:
        candidates, protected = self._recipe_candidates(event, constructables, cs, user_msg)
        self._discard_proposed_consumption(event, protected)
        explicit = bool(event.combination_result_id or event.combination_ingredient_ids)
        if len(candidates) != 1:
            if len(candidates) > 1 or explicit:
                cs.messages.append("Crafting requires one known result item ID.")
            return
        ent = candidates[0]
        needed = _ingredients(ent)
        if not self._is_craftable(ent, needed, cs):
            if explicit:
                cs.messages.append(
                    "The selected recipe is unavailable or its ingredients cannot be reached."
                )
            return
        blocked = await self._craft_guard_blocks(ent)
        if blocked is not None:
            cs.messages.extend(blocked)
            return
        await self._craft(event, ent, needed, cs)

    @staticmethod
    def _violation(kind: str, ent: WorldEntity | None, cid: str, fallback_name: str) -> str:
        name = ent.name if ent else fallback_name
        ingredients = ", ".join(ent.combination_ingredients or []) if ent else ""
        actions = {
            "inventory": "add constructable item '{name}' ({cid}) to inventory",
            "spawn": "spawn constructable item '{name}' ({cid}) in scene",
            "reveal": "reveal constructable entity '{name}' ({cid})",
        }
        action = actions[kind].format(name=name, cid=cid)
        return f"Rule Violation: Attempted to {action} without combining its ingredients: {ingredients or 'unknown'}."

    def _strip_items(
        self, items: list, cid: str, ent: WorldEntity | None, kind: str | None, messages: list[str]
    ) -> list:
        """Removes the constructable from a GM item list, recording a violation if ``kind`` is set."""
        kept = []
        for item in items:
            if item_id_upper(item) != cid:
                kept.append(item)
            elif kind:
                messages.append(self._violation(kind, ent, cid, item.name))
        return kept

    def _strip_entity_changes(
        self, event: GameEvent, cid: str, ent: WorldEntity | None, messages: list[str]
    ) -> None:
        def is_constructable(entity_id: str | None) -> bool:
            return entity_id is not None and entity_id.upper() == cid

        if event.updated_entities:
            for up in event.updated_entities:
                if is_constructable(up.entity_id) and up.is_hidden is False:
                    messages.append(self._violation("reveal", ent, cid, up.entity_id))
            event.updated_entities = [
                up for up in event.updated_entities if not is_constructable(up.entity_id)
            ]
        if event.moved_entities:
            event.moved_entities = [
                m for m in event.moved_entities if not is_constructable(m.entity_id)
            ]

    def _revert_illegal_constructable(
        self, event: GameEvent, cid: str, ent: WorldEntity | None, messages: list[str]
    ) -> None:
        if event.new_inventory_items:
            event.new_inventory_items = self._strip_items(
                event.new_inventory_items, cid, ent, "inventory", messages
            )
        if event.updated_inventory_items:
            event.updated_inventory_items = self._strip_items(
                event.updated_inventory_items, cid, ent, None, messages
            )
        if event.spawned_items:
            event.spawned_items = self._strip_items(
                event.spawned_items, cid, ent, "spawn", messages
            )
        self._strip_entity_changes(event, cid, ent, messages)

    async def _enforce_constructable_combination(
        self, event: GameEvent, user_msg: str
    ) -> list[str]:
        """Crafts constructables on a combine action and reverts any the GM produced without crafting."""
        entities = await self._session_entities()
        constructables = [
            e for e in entities if e.id and str(e.item_type or "").upper() == "CONSTRUCTABLE"
        ]
        if not constructables:
            return []
        cs = self._crafting_state(entities)
        if event.combination_intent:
            await self._try_craft(event, constructables, cs, user_msg)

        by_id = {e.id.upper(): e for e in constructables}
        for cid, ent in by_id.items():
            if cid not in cs.constructed and self._is_hidden_now(ent):
                self._revert_illegal_constructable(event, cid, ent, cs.messages)
        return cs.messages
