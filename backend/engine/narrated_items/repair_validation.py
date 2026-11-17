"""Preview corrections with existing domain validators before accepting their effects."""

import logging
from dataclasses import dataclass
from typing import Any

from backend.engine.narrated_items import coverage, evidence, independent_state
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.observation_sources import verified_sources
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.narrated_items.source_catalog import Catalog
from backend.engine.npc_actions.reconciliation import protect as protect_commands
from backend.engine.physical_conditions.ledger import apply as apply_conditions
from backend.engine.physical_conditions.ledger import read as read_conditions
from backend.engine.physical_conditions.references import bind_records
from backend.engine.turn_replay.transactions import release_for_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Check:
    manager: Any
    actors: dict
    snapshot: Any
    catalog: Catalog
    item_targets: frozenset[str]
    staging: bool
    detailed: bool
    message_id: str
    player_message: tuple[str, str] | None
    item_changes_allowed: bool
    blocked_targets: frozenset[str] = frozenset()

    async def __call__(self, candidate: ItemExtraction, original: ItemExtraction) -> bool:
        """All operations run on copies; rejected additions cannot unconfirm old facts."""
        try:
            valid = await self._valid(candidate, original)
            if valid and candidate is original:
                await release_for_model(self.manager)
            return valid
        except Exception as exc:
            logger.warning("State correction preview failed (%s).", type(exc).__name__)
            return False

    async def _valid(self, candidate: ItemExtraction, original: ItemExtraction) -> bool:
        body, audit = coverage.inspect(candidate, self.catalog, staging=self.staging)
        if audit.blocked:
            return False
        bound = evidence.bind(body, self.catalog.narration, catalog=self.catalog)
        extracted, failures, denied, indices = independent_state.unpack(bound, self.actors)
        extracted, indices, command_errors = protect_commands(self.manager, extracted, indices)
        if (
            command_errors
            or failures
            or denied
            or (extracted.actions and not self.item_changes_allowed)
        ):
            return False
        if self._blocked(extracted) or _item_chain_conflict(extracted, len(original.actions)):
            return False
        _, accepted, errors = apply_actions(
            extracted,
            self.actors,
            self.snapshot,
            self.catalog.narration,
            detailed=self.detailed,
            session_id=self.manager.state.session_id,
            message_id=self.message_id,
            source_indices=indices,
            verified_sources=await verified_sources(self.manager, extracted, self.actors),
        )
        added_indices = set(range(len(original.actions), len(candidate.actions)))
        if errors or not added_indices <= {row["action_index"] for row in accepted}:
            return False
        before = read_conditions(self.manager.state.entity_states)
        proposals, _ = bind_records(before, extracted.condition_updates)
        changed, accepted_conditions, rejected = apply_conditions(
            self.manager.state.entity_states,
            proposals,
            targets=set(self.actors) | self.item_targets,
            item_targets=set(self.item_targets),
            narration=self.catalog.narration,
            message_id=self.message_id,
            session_id=self.manager.state.session_id,
            minute=int(getattr(self.manager.state, "in_game_time", 0) or 0),
            player_message=self.player_message,
        )
        count = len(original.condition_updates)
        previous = set(accepted_conditions[:count])
        added = accepted_conditions[count:]
        if rejected or previous & set(added) or len(added) != len(set(added)):
            return False
        after = read_conditions(changed)
        return all(_changed(before.conditions.get(key), after.conditions[key]) for key in added)

    def _blocked(self, extraction: ItemExtraction) -> bool:
        if not self.blocked_targets:
            return False
        _, rejected = independent_state.select(
            self.manager,
            extraction,
            set(self.blocked_targets),
            set(self.actors) | self.item_targets,
        )
        return bool(rejected)


def _item_chain_conflict(extraction: ItemExtraction, count: int) -> bool:
    original = {row.item_id for row in extraction.actions[:count]} - {None}
    additional = {row.item_id for row in extraction.actions[count:]} - {None}
    return bool(original & additional)


def _changed(previous: Any, current: Any) -> bool:
    if previous is None:
        return True
    fields = {"target_id", "kind", "part", "status", "detail", "visibility"}
    if current.kind != "item_state":
        fields.update({"visual_detail", "visual_region"})
    return bool(previous.model_dump(include=fields) != current.model_dump(include=fields))
