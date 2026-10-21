"""Context enrichment for image generation prompts.

Protagonist, NPC, item and cover prompts carry the optional ``appearance`` keywords
(max 100 chars). Scene images are described by their decorative objects and the
NPCs placed in the scene; protagonist portraits borrow setting and mood from the plot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import prompts

MAX_APPEARANCE_LENGTH = 100
MAX_SCENE_DECORATIONS = 7
MAX_SCENE_NPCS = 4
MAX_NPC_DESCRIPTION_LENGTH = 160
MAX_PLOT_CONTEXT_LENGTH = 1000


def _clip(text: Any, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def clean_appearance(value: Any) -> Optional[str]:
    """Normalizes appearance keywords to a single line of at most 100 characters (None if empty)."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:MAX_APPEARANCE_LENGTH].strip()
    return text or None


def appearance_context(appearance: Any) -> str:
    keywords = clean_appearance(appearance)
    if not keywords:
        return ""
    return prompts.IMAGE_APPEARANCE_TEMPLATE.format(appearance=keywords.rstrip("."))


def _npc_phrase(npc: Mapping[str, Any]) -> str:
    name = _clip(npc.get("name"), 100)
    looks = clean_appearance(npc.get("appearance")) or _clip(
        npc.get("description"), MAX_NPC_DESCRIPTION_LENGTH
    )
    if not looks:
        return name
    return f"{name} ({looks})"


def scene_context(
    decorative_objects: Optional[Iterable[Any]] = None,
    npcs: Optional[Iterable[Mapping[str, Any]]] = None,
) -> str:
    """Returns visual details for a scene prompt, or an empty string when there are none."""
    items = [_clip(d, 100) for d in decorative_objects or [] if isinstance(d, str) and d.strip()]
    phrases = [_npc_phrase(npc) for npc in npcs or [] if npc.get("name")]
    parts: list[str] = []
    if items:
        parts.append(
            prompts.SCENE_IMAGE_DECORATIONS_TEMPLATE.format(
                items=", ".join(items[:MAX_SCENE_DECORATIONS])
            )
        )
    if phrases:
        parts.append(
            prompts.SCENE_IMAGE_NPCS_TEMPLATE.format(npcs="; ".join(phrases[:MAX_SCENE_NPCS]))
        )
    return " ".join(parts)


def protagonist_context(plot: Optional[str], appearance: Any = None) -> str:
    """Returns appearance keywords plus the plot-derived setting hint for a protagonist portrait."""
    parts = [appearance_context(appearance)]
    excerpt = _clip(plot, MAX_PLOT_CONTEXT_LENGTH)
    if excerpt:
        parts.append(prompts.PROTAGONIST_IMAGE_PLOT_TEMPLATE.format(plot=excerpt))
    return " ".join(part for part in parts if part)


def with_context(context: str) -> str:
    """Formats an optional context sentence for the ``{context}`` template slot."""
    return f"{context} " if context else ""


def _sentence_body(text: Optional[str]) -> str:
    """Drops trailing periods because the templates add their own."""
    return (text or "").strip().rstrip(".").rstrip()


def build_scene_image_prompt(
    name: str,
    description: str,
    decorative_objects: Optional[Iterable[Any]] = None,
    npcs: Optional[Iterable[Mapping[str, Any]]] = None,
) -> str:
    return prompts.SCENE_IMAGE_PROMPT_TEMPLATE.format(
        name=name,
        description=_sentence_body(description),
        context=with_context(scene_context(decorative_objects, npcs)),
    )


def build_protagonist_image_prompt(
    name: str,
    role: str,
    description: str,
    plot: Optional[str] = None,
    appearance: Any = None,
) -> str:
    return prompts.PROTAGONIST_IMAGE_PROMPT_TEMPLATE.format(
        name=name,
        role=role,
        description=_sentence_body(description),
        context=with_context(protagonist_context(plot, appearance)),
    )


def build_npc_image_prompt(name: str, description: str, appearance: Any = None) -> str:
    return prompts.NPC_IMAGE_PROMPT_TEMPLATE.format(
        name=name,
        description=_sentence_body(description),
        context=with_context(appearance_context(appearance)),
    )


def build_object_image_prompt(name: str, description: str, appearance: Any = None) -> str:
    return prompts.OBJECT_IMAGE_PROMPT_TEMPLATE.format(
        name=name,
        description=_sentence_body(description),
        context=with_context(appearance_context(appearance)),
    )


def manifest_scene_npcs(
    npcs: Iterable[Mapping[str, Any]], scene_id: str, default_scene_id: str
) -> list[Mapping[str, Any]]:
    """Visible manifest NPCs starting in the given scene (same fallback as NPC persistence)."""
    return [
        npc
        for npc in npcs
        if not npc.get("is_hidden")
        and (npc.get("start_scene_id") or npc.get("current_scene_id") or default_scene_id)
        == scene_id
    ]


async def load_scene_npcs(
    db: AsyncSession, template_id: str, scene_id: str
) -> list[dict[str, Any]]:
    """Visible template NPCs currently placed in the given scene."""
    from backend.models.world_entity import WorldEntity

    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == template_id,
            WorldEntity.session_id.is_(None),
            WorldEntity.entity_type == "NPC",
            WorldEntity.current_scene_id == scene_id,
            WorldEntity.is_hidden.is_(False),
        )
    )
    return [
        {"name": entity.name, "description": entity.description, "appearance": entity.appearance}
        for entity in res.scalars().all()
    ]
