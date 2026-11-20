"""Hidden entity reveal: hidden things in the scene appear once they are discovered."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from pydantic import BaseModel

from backend.core.prompts import HIDDEN_ENTITY_DISCOVERY_SYSTEM_PROMPT
from backend.engine.gameplay.guardrails.base import GuardrailBase, GuardrailNotice, entity_view
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.mutation_targets import TargetIndex
from backend.engine.rule_engine import GameEvent
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)


class DiscoveryCheckResponse(BaseModel):
    discovered: bool


def _granted_ids(items: Iterable[object], catalog: TargetIndex) -> set[str]:
    """Resolve legacy name-only grants once. An explicit ID always takes precedence."""
    grants = set()
    for item in items:
        raw_id = getattr(item, "id", None)
        if raw_id and raw_id not in catalog.ids and raw_id.casefold() not in catalog.folded_ids:
            continue
        identifier = catalog.resolve(raw_id or getattr(item, "name", None))
        if identifier:
            grants.add(identifier)
    return grants


def _parent_reveals(event: GameEvent, ent: WorldEntity, by_id: dict[str, WorldEntity]) -> bool:
    """True when an entity updated this turn reveals or hides this one (``reveals_item_id`` / ``##PARENT`` tags)."""
    position = str(ent.spatial_position or "")
    rule = str(ent.reveal_rule or "")
    for up in event.updated_entities or []:
        if not up.entity_id:
            continue
        parent = by_id.get(up.entity_id)
        if (
            parent
            and parent.reveals_item_id
            and parent.reveals_item_id.strip().upper() == ent.id.upper()
        ):
            return True
        # Authored positions may reference a bare parent ID; rules use a tagged reference.
        parent_id = re.escape(up.entity_id)
        tag = rf"##{parent_id}(?![\w-])"
        if (
            re.search(tag, position, re.IGNORECASE)
            or re.search(tag, rule, re.IGNORECASE)
            or re.search(rf"(?<![\w#-]){parent_id}(?![\w-])", position)
        ):
            return True
    return False


class RevealGuardMixin(GuardrailBase):
    """Reveals hidden scene entities that the turn discovered."""

    def _is_entity_hidden_now(self, ent: WorldEntity) -> bool:
        override = (self.state.entity_states or {}).get(ent.id, {})
        if override.get("is_hidden") is not None:
            return bool(override["is_hidden"])
        return bool(ent.is_hidden)

    def _hidden_scene_entities(self, entities: list[WorldEntity]) -> list[WorldEntity]:
        contained = AdventureLogic.collect_container_item_ids(
            [{"item_type": e.item_type, "inventory": e.inventory} for e in entities]
        )
        return [
            e
            for e in entities
            if e.id
            and (view := entity_view(e, self.state.entity_states or {})).scene_id
            == self.state.current_scene_id
            and not view.in_inventory
            and str(e.id) not in contained
            and str(e.item_type or "").upper() != "CONSTRUCTABLE"
            and self._is_entity_hidden_now(e)
        ]

    async def _llm_says_discovered(self, ent: WorldEntity, user_msg: str, narration: str) -> bool:
        """Language-agnostic fallback: asks the small model whether the turn discovered the entity."""
        try:
            llm, model = self._small_llm()
            res = await llm.aexecute_complex_task(
                system_prompt=HIDDEN_ENTITY_DISCOVERY_SYSTEM_PROMPT,
                user_prompt=(
                    f"Hidden Entity ID: {ent.id}\n"
                    f"Hidden Entity Name: {ent.name}\n"
                    f"Entity Hidden At/Reveal Rule: {ent.spatial_position or ''} {ent.reveal_rule or ''}\n"
                    f'Player Message: "{user_msg}"\n'
                    f'Game Master Narration: "{narration}"'
                ),
                model=model,
                response_model=DiscoveryCheckResponse,
            )
        except Exception as exc:
            logger.error("Error checking hidden entity discovery with LLM: %s", exc)
            return False
        if isinstance(res, DiscoveryCheckResponse):
            return res.discovered
        return bool(res.get("discovered", False)) if isinstance(res, dict) else False

    async def _should_reveal(
        self,
        event: GameEvent,
        ent: WorldEntity,
        by_id: dict[str, WorldEntity],
        user_msg: str,
        narration: str,
        grants: set[str],
    ) -> bool:
        discovered = {
            str(e).strip().upper() for e in getattr(event, "discovered_entity_ids", []) or []
        }
        if ent.id.upper() in discovered:
            return True
        if ent.id in grants:
            return True
        if _parent_reveals(event, ent, by_id):
            return True
        if not (user_msg or narration):
            return False
        return await self._llm_says_discovered(ent, user_msg, narration)

    async def _enforce_hidden_entity_reveal(
        self, event: GameEvent, user_msg: str, draft_narration: str = ""
    ) -> list[str]:
        """Auto-reveals hidden entities in the current scene that this turn discovered."""
        entities = await self._session_entities()
        hidden = self._hidden_scene_entities(entities)
        if not hidden:
            return []
        by_id = {e.id: e for e in entities if e.id}
        catalog = TargetIndex([{"id": e.id, "name": e.name} for e in entities])
        grants = _granted_ids(
            [*(event.spawned_items or []), *(event.new_inventory_items or [])], catalog
        )
        revealed: list[str] = []
        for ent in hidden:
            already = any(
                (up.entity_id or "").upper() == ent.id.upper() and up.is_hidden is False
                for up in event.updated_entities or []
            )
            if already or not await self._should_reveal(
                event, ent, by_id, user_msg, draft_narration, grants
            ):
                continue
            self._upsert_entity_update(event, ent.id, is_hidden=False)
            revealed.append(GuardrailNotice(f"Revealed {ent.name}"))
            logger.info(
                "[Turn %s] Auto-revealed hidden entity '%s' (%s) in scene '%s'",
                self.game_id,
                ent.id,
                ent.name,
                self.state.current_scene_id,
            )
        return revealed
