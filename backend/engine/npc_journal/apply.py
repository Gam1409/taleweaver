"""Validate extraction evidence and apply only session-owned character knowledge."""

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.npc_journal.records import (
    JOURNAL_KEY,
    append_observations,
    is_significant,
    journal_of,
    normalized,
    supported_quote,
)
from backend.engine.npc_journal.schema import CharacterObservation, JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldScene


def _resolve(character: CharacterObservation, npcs: list[WorldEntity]) -> WorldEntity | None:
    if character.npc_id:
        return next((npc for npc in npcs if npc.id == character.npc_id), None)
    matches = [npc for npc in npcs if normalized(npc.name) == normalized(character.name)]
    return matches[0] if len(matches) == 1 else None


def _introduction(character: CharacterObservation, message: ChatMessage) -> bool:
    quote = normalized(character.self_introduction or "")
    name = normalized(character.name)
    return (
        supported_quote(character.self_introduction, message.content)
        and name in quote
        and len(quote) > len(name) + 2
    )


def _new_npc(character: CharacterObservation, message: ChatMessage) -> WorldEntity:
    return WorldEntity(
        id=str(uuid4()),
        session_id=message.session_id,
        template_id=None,
        entity_type="NPC",
        name=character.name.strip(),
        description="",
        current_scene_id=message.scene_id,
        npc_type="BEING",
        movement_type="MOVABLE",
        moveable=True,
        allowed_scenes=[],
        is_hidden=False,
        is_in_inventory=False,
        is_attackable=False,
        is_killable=False,
        inventory=[],
        metadata_json={
            JOURNAL_KEY: {
                "version": 1,
                "origin": "introduced",
                "introduced_message_id": message.id,
                "introduction": character.self_introduction,
                "portrait_status": "pending",
                "declared_name": character.name,
                "entries": [],
                "aliases": [],
            }
        },
    )


async def apply_extraction(
    db: AsyncSession, message: ChatMessage, result: JournalExtraction, player_name: str
) -> list[str]:
    """Return IDs of newly created NPCs. Caller commits knowledge and task completion together."""
    scene = await db.scalar(
        select(WorldScene.pk).where(
            WorldScene.session_id == message.session_id, WorldScene.id == message.scene_id
        )
    )
    if scene is None:
        return []
    npcs = list(
        (
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.session_id == message.session_id, WorldEntity.entity_type == "NPC"
                )
            )
        ).all()
    )
    created = []
    for character in result.characters:
        npc = await _apply_character(db, message, character, npcs, player_name)
        if npc is not None:
            npcs.append(npc)
            created.append(npc.id)
    return created


async def _apply_character(
    db: AsyncSession,
    message: ChatMessage,
    character: CharacterObservation,
    npcs: list[WorldEntity],
    player_name: str,
) -> WorldEntity | None:
    if normalized(character.name) == normalized(player_name):
        return None
    npc = _resolve(character, npcs)
    if character.npc_id and npc is None:
        return None
    # Never merge two characters with the same name or expose a hidden template NPC.
    if npc is not None and npc.is_hidden:
        return None
    created = npc is None
    if created and (
        not _introduction(character, message)
        or any(normalized(n.name) == normalized(character.name) for n in npcs)
    ):
        return None
    if created:
        npc = _new_npc(character, message)
        db.add(npc)
    if (
        not created
        and _introduction(character, message)
        and normalized(character.name) != normalized(npc.name)
    ):
        character = character.model_copy(update={"aliases": [*character.aliases, character.name]})
    append_observations(npc, character, message)
    _update_appearance(npc, character, message)
    return npc if created else None


def _update_appearance(npc: Any, character: CharacterObservation, message: ChatMessage) -> None:
    # Only dynamically introduced characters get an observed portrait description.
    # Authored/template descriptions and runtime stat overrides retain their ownership.
    if journal_of(npc).get("origin") != "introduced":
        return
    appearances = [
        o.text
        for o in character.observations
        if o.category == "appearance"
        and o.source == "observed"
        and is_significant(o)
        and supported_quote(o.evidence, message.content)
    ]
    if appearances and not npc.description:
        npc.description = " ".join(appearances)[:1000]
        journal = journal_of(npc)
        journal.update(description_source=message.id, observed_description=npc.description)
        npc.metadata_json = {**(npc.metadata_json or {}), JOURNAL_KEY: journal}
