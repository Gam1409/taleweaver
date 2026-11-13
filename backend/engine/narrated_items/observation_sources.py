"""Verify bounded prior placement proofs without another model request."""

from typing import Any

from sqlalchemy import select

from backend.engine.clothing.body_schema import WearSource
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.wear_provenance import source_matches
from backend.engine.debug_transcript import not_debug_sql
from backend.engine.narrated_items.schema import ItemExtraction
from backend.models.chat import ChatMessage


def _bindings(extraction: ItemExtraction, actors: dict) -> dict[tuple[str, str], WearSource]:
    result = {}
    for action in extraction.actions[:6]:
        if action.basis not in {"observed_wear", "observed_placement"} or not action.item_id:
            continue
        if action.basis == "observed_wear" and not (
            action.uncovered_regions or action.attachment_slot
        ):
            continue
        actor = actors.get(action.destination_owner)
        profile = load_profile(actor.get("visual_profile")) if actor else None
        if profile is None:
            continue
        row = next((row for row in profile.worn if row.item_id == action.item_id), None)
        if row is not None and row.source is not None and row.source.source_message_id:
            result[(action.destination_owner, action.item_id)] = row.source
    return result


async def verified_sources(
    manager: Any, extraction: ItemExtraction, actors: dict
) -> set[tuple[str, str]]:
    """Only source-valid saved bindings may suppress a fresh current observation."""
    bindings = _bindings(extraction, actors)
    identifiers = {source.source_message_id for source in bindings.values()}
    if not identifiers:
        return set()
    messages = await manager.db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.state.session_id,
            ChatMessage.id.in_(identifiers),
            ChatMessage.role.in_(["assistant", "user"]),
            not_debug_sql(),
        )
        .execution_options(populate_existing=True)
    )
    sources = {message.id: message for message in messages}
    return {
        key
        for key, source in bindings.items()
        if (message := sources.get(source.source_message_id)) is not None
        and message.role == source.source_role
        and source_matches(source.model_dump(), message.content)
    }
