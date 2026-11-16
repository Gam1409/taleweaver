"""Evidence survives copying; changed or missing narration never stays confirmed."""

from copy import deepcopy
from typing import Any

from .ledger import read
from .schema import KEY


def retract(state: Any, message_id: str) -> None:
    if KEY not in (state.entity_states or {}):
        return
    ledger = read(state.entity_states)
    for row in ledger.records.values():
        if any(
            source.kind == "narration" and source.source_id == message_id
            for source in (row.origin, row.latest)
        ):
            row.status = "unconfirmed"
    if ledger.frame_message_id == message_id:
        ledger.frame_actions = []
        ledger.frame_message_id = ""
    if ledger.last_check.get("message_id") == message_id:
        ledger.last_check = {}
    state.entity_states = {**state.entity_states, KEY: ledger.model_dump()}


def remap(states: dict | None, message_ids: dict[str, str]) -> dict:
    result = deepcopy(states or {})
    if KEY not in result:
        return result
    ledger = read(result)
    for row in ledger.records.values():
        for source in (row.origin, row.latest):
            _remap_source(row, source, message_ids)
    ledger.frame_message_id = message_ids.get(ledger.frame_message_id, "")
    if not ledger.frame_message_id:
        ledger.frame_actions = []
    ledger.last_check["message_id"] = message_ids.get(ledger.last_check.get("message_id", ""), "")
    result[KEY] = ledger.model_dump()
    return result


def _remap_source(row: Any, source: Any, message_ids: dict[str, str]) -> None:
    if source.kind != "narration":
        return
    source.source_id = message_ids.get(source.source_id, "")
    if not source.source_id:
        source.kind = "unavailable"
        row.status = "unconfirmed"
