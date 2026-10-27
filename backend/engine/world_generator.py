"""
World generation orchestrator (facade).

This module is the public entry point for world generation. The actual
implementation is split across focused sub-modules:

- ``backend.engine.world_schemas``      — Pydantic schemas for LLM output.
- ``backend.engine.world_prompt_builder`` — Builds the LLM system/user prompts.
- ``backend.engine.world_manifest_applier`` — Persists the manifest to the DB.

All previously public symbols are re-exported here so existing imports remain
unaffected.
"""

import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.adventure_format import CURRENT_VERSION
from backend.core.config import settings
from backend.core.game_modes import mode_policy, normalize_vn_template
from backend.core.llm_logger import log_structured_event
from backend.core.llm_router import GameMasterLLM
from backend.engine.clothing.generation import generation_instruction
from backend.engine.vn_world_generation import normalize_vn_generated_manifest
from backend.engine.world_generation_persistence import (
    load_cover_source_assets,
    persist_generated_narrative,
)
from backend.engine.world_object_constraints import constrain_generated_objects

# --- Re-exports so existing imports stay valid ---
from backend.engine.world_schemas import (  # noqa: F401
    AwardTemplateSchema,
    EquipmentSchema,
    ProtagonistSchema,
    QuestSchema,
    WorldExitSchema,
    WorldManifesto,
    WorldNPCSchema,
    WorldObjectSchema,
    WorldSceneSchema,
)
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.utils.path_security import sanitize_path_component
from backend.utils.text_utils import slugify

logger = logging.getLogger(__name__)

IMAGE_MODERATION_MARKERS = (
    "safety filter",
    "content moderated",
    "moderated",
    "content policy",
    "policy violation",
    "blocked by safety",
    "responsible ai",
    "prompt blocked",
)


# ---------------------------------------------------------------------------
# Module-level utilities (kept here: used by tests & other modules directly)
# ---------------------------------------------------------------------------


def is_image_moderation_error(error: Exception | str | None) -> bool:
    if error is None:
        return False
    message = str(error).lower()
    return any(marker in message for marker in IMAGE_MODERATION_MARKERS)


def _build_voice_assignment_requirement(
    enabled: bool,
    available_voice_list: Optional[list[str]] = None,
) -> str:
    return ""


def _image_generation_timeout_seconds() -> float:
    raw_timeout = getattr(settings, "IMAGE_GENERATION_TIMEOUT_SECONDS", 600)
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = 120.0
    return max(10.0, timeout)


def _validate_t2i_prerequisites(
    user: Optional[User],
    *,
    need_scene_images: bool,
    need_npc_images: bool,
    need_item_images: bool,
    need_protagonist_image: bool,
) -> None:
    from backend.engine.image_profiles import validate_image_profiles

    requested = {
        "scene": need_scene_images,
        "npc": need_npc_images,
        "object": need_item_images,
        "protagonist": need_protagonist_image,
    }
    kinds = [kind for kind, enabled in requested.items() if enabled]
    if kinds:
        validate_image_profiles(user, [*kinds, "cover"])


async def _publish_generation_status(
    db: AsyncSession,
    adventure: Optional[AdventureTemplate],
    status: str,
) -> None:
    """Persist live status text; raise GenerationCancelled if user cancelled."""
    if not adventure:
        return
    from backend.engine.generation_control import guard_generation_write

    await db.refresh(adventure)
    logs = list(adventure.generation_logs or [])
    logs.append(
        {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "type": "status",
            "content": status,
        }
    )
    await guard_generation_write(db, adventure, creation_status=status, generation_logs=logs)
    await db.commit()
    await db.refresh(adventure)


async def _log_image_generation(
    db: AsyncSession,
    adventure: Optional[AdventureTemplate],
    prompt: str,
    image_url: str,
) -> None:
    """Log AI-generated image prompt and URL."""
    if not adventure or not image_url or image_url.startswith("assets/"):
        return
    logs = list(adventure.generation_logs or [])
    logs.append(
        {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "type": "image_generation",
            "content": prompt,
            "image_url": image_url,
        }
    )
    from backend.engine.generation_control import generation_run, guard_generation_write

    if generation_run.get() is not None:
        await guard_generation_write(db, adventure)
    adventure.generation_logs = logs  # type: ignore[assignment]
    await db.commit()
    await db.refresh(adventure)


async def _log_reused_asset(
    db: AsyncSession,
    adventure: Optional[AdventureTemplate],
    entity_name: str,
    image_url: str,
) -> None:
    """Log reused/copied visual asset."""
    if not adventure or not image_url or image_url.startswith("assets/"):
        return
    logs = list(adventure.generation_logs or [])
    logs.append(
        {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "type": "image_generation",
            "content": f"Reused source asset: {entity_name}",
            "image_url": image_url,
        }
    )
    from backend.engine.generation_control import generation_run, guard_generation_write

    if generation_run.get() is not None:
        await guard_generation_write(db, adventure)
    adventure.generation_logs = logs  # type: ignore[assignment]
    await db.commit()
    await db.refresh(adventure)


async def _publish_generation_status_with_callback(
    db: AsyncSession,
    adventure: Optional[AdventureTemplate],
    status: str,
    status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> None:
    """Persist generation status and optionally forward it to an external observer."""
    await _publish_generation_status(db, adventure, status)
    if status_callback:
        try:
            await status_callback(status)
        except Exception as exc:
            logger.warning("Generation status callback failed for %s: %s", status, exc)


def _uses_ollama_t2i(user: Optional[User]) -> bool:
    if not user:
        return False
    t2i_settings = user.t2i_settings or {}
    return (t2i_settings.get("provider") or "").lower() == "ollama"


def _normalize_text_log_content(
    raw_content: Any,
    description_fallback: Any = "",
    name_fallback: Any = "",
) -> str:
    """Normalize readable text while preserving paragraph breaks and enforcing length."""
    content = str(raw_content or "")
    if not content.strip():
        content = str(description_fallback or "")
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines = [line.rstrip() for line in content.split("\n")]
    normalized = "\n".join(normalized_lines).strip()
    if not normalized:
        safe_name = str(name_fallback or "This note").strip() or "This note"
        normalized = f"{safe_name} contains faded but readable notes."
    return normalized[:500]


def _normalize_unlock_requirements(
    raw_code: Any,
    raw_item: Any,
    raw_rule: Any,
) -> tuple[str, str, str]:
    """Normalize unlock requirements and enforce mutual exclusivity (code > item > rule)."""
    code_to_unlock = str(raw_code or "").strip()
    item_to_unlock = str(raw_item or "").strip().upper()
    rule_to_unlock = str(raw_rule or "").strip()

    if code_to_unlock:
        code_to_unlock = code_to_unlock[:32]
        item_to_unlock = ""
        rule_to_unlock = ""
    elif item_to_unlock:
        item_to_unlock = slugify(item_to_unlock).upper().replace("-", "_")[:64]
        code_to_unlock = ""
        rule_to_unlock = ""
    elif rule_to_unlock:
        rule_to_unlock = rule_to_unlock[:500]
        code_to_unlock = ""
        item_to_unlock = ""
    else:
        code_to_unlock = ""
        item_to_unlock = ""
        rule_to_unlock = ""

    return code_to_unlock, item_to_unlock, rule_to_unlock


def _extract_item_id(entry: Any) -> Optional[str]:
    if isinstance(entry, str):
        normalized = entry.strip()
        return normalized or None
    if isinstance(entry, dict):
        for key in ("id", "item_id", "object_id"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _normalize_container_inventories(container_objs, object_ids_set):
    assigned_ids: set[str] = set()
    for container in container_objs:
        container_id = str(container.get("id") or "").strip()
        raw_inventory = container.get("inventory")
        normalized_inventory: list[str] = []
        if isinstance(raw_inventory, list):
            for entry in raw_inventory:
                item_id = _extract_item_id(entry)
                if not item_id or item_id not in object_ids_set or item_id == container_id:
                    continue
                if item_id in normalized_inventory:
                    continue
                normalized_inventory.append(item_id)
        container["inventory"] = normalized_inventory
        assigned_ids.update(normalized_inventory)

    return assigned_ids


def _ensure_containers_have_minimum_inventory(objects: list[dict[str, Any]]) -> None:
    """Ensure every generated CONTAINER references at least one item ID in inventory.

    Only reuses existing valid item IDs; never fabricates new items.
    """
    if not isinstance(objects, list) or not objects:
        return

    container_objs: list[dict[str, Any]] = []
    object_ids_in_order: list[str] = []
    seen_ids: set[str] = set()

    for obj in objects:
        if not isinstance(obj, dict):
            continue
        obj_id = str(obj.get("id") or "").strip()
        if obj_id and obj_id not in seen_ids:
            seen_ids.add(obj_id)
            object_ids_in_order.append(obj_id)
        if str(obj.get("item_type") or "").upper() == "CONTAINER":
            container_objs.append(obj)

    if not container_objs:
        return

    object_ids_set = set(object_ids_in_order)
    candidate_item_ids = [
        str(obj.get("id") or "").strip()
        for obj in objects
        if isinstance(obj, dict)
        and str(obj.get("id") or "").strip()
        and str(obj.get("item_type") or "").upper() != "CONTAINER"
    ]

    assigned_ids = _normalize_container_inventories(container_objs, object_ids_set)

    unassigned_candidates = [iid for iid in candidate_item_ids if iid not in assigned_ids]
    for container in container_objs:
        if container.get("inventory"):
            continue
        if unassigned_candidates:
            chosen_item_id = unassigned_candidates.pop(0)
            container["inventory"] = [chosen_item_id]
            assigned_ids.add(chosen_item_id)


# ---------------------------------------------------------------------------
# WorldGenerator (public API facade)
# ---------------------------------------------------------------------------


def _world_generator_llm(user, provider, model):
    configured = user.llm_settings or {}
    provider_keys = (
        "generator_model_provider",
        "complex_model_provider",
        "small_model_provider",
        "preferred_provider",
    )
    if not provider and not any(configured.get(key) for key in provider_keys):
        raise ValueError(
            "No adventure generator LLM provider configured for this user. "
            "Open Settings -> Intelligence and set Generator Model Provider."
        )
    return GameMasterLLM.for_role(user, "generator", provider=provider, model=model)


class WorldGenerator:
    @staticmethod
    def preprocess_manifest_object_ids(manifest_dict):
        from backend.engine.world_manifest_text import preprocess_manifest_object_ids

        return preprocess_manifest_object_ids(manifest_dict)

    @staticmethod
    def _extract_sequences_from_prompt(prompt_str):
        from backend.engine.world_manifest_text import _extract_sequences_from_prompt

        return _extract_sequences_from_prompt(prompt_str)

    @staticmethod
    async def generate_world(
        db: AsyncSession,
        user: User,
        template_id: str,
        title: str,
        original_prompt: str,
        sequences: Optional[list[dict[str, Any]]] = None,
        min_sequences: Optional[int] = None,
        max_sequences: Optional[int] = None,
        generation_strictness: Literal["strict", "creative"] = "creative",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        generate_scene_images: bool = False,
        generate_npc_images: bool = False,
        generate_item_images: bool = False,
        automatic_npc_voice_assignment: bool = True,
        min_scenes: Optional[int] = None,
        max_scenes: Optional[int] = None,
        container_generation_enabled: bool = True,
        scripts_generation_enabled: bool = True,
        min_containers: Optional[int] = None,
        max_containers: Optional[int] = None,
        text_log_generation_enabled: bool = True,
        min_text_logs: Optional[int] = None,
        max_text_logs: Optional[int] = None,
        quest_generation_enabled: bool = True,
        min_quests: Optional[int] = None,
        max_quests: Optional[int] = None,
        min_items: Optional[int] = None,
        max_items: Optional[int] = None,
        award_generation_enabled: bool = True,
        min_awards: Optional[int] = None,
        max_awards: Optional[int] = None,
        can_damage_npcs: bool = True,
        npcs_can_damage_protagonist: bool = True,
        selected_image_styles: Optional[list[str]] = None,
        selected_tone: Optional[str] = None,
        language: Optional[str] = None,
        cover_source_manifest: Optional[dict[str, Any]] = None,
        cover_source_adventure_id: Optional[str] = None,
        cover_source_adventure_name: Optional[str] = None,
        cover_similarity_percent: int = 50,
        allow_reuse_source_assets: bool = True,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        rule_enforcement_mode: str | None = None,
    ) -> None:
        """Call the LLM to generate a coherent world and persist it to the DB.

        Persists the result to the WorldScene, WorldExit, and WorldEntity tables.
        """

        from backend.engine.world_manifest_applier import apply_manifest  # noqa: PLC0415
        from backend.engine.world_prompt_builder import (
            build_world_generation_prompts,  # noqa: PLC0415
        )

        if not template_id or sanitize_path_component(template_id) != template_id:
            raise ValueError("Invalid template_id")
        if (
            cover_source_adventure_id
            and sanitize_path_component(cover_source_adventure_id) != cover_source_adventure_id
        ):
            raise ValueError("Invalid cover_source_adventure_id")

        adventure = await db.get(AdventureTemplate, template_id)
        effective_mode = rule_enforcement_mode or getattr(adventure, "rule_enforcement_mode", None)
        policy = mode_policy(effective_mode)
        if policy.vn and adventure:
            adventure.rule_enforcement_mode = "vn"
            normalize_vn_template(adventure)
        if policy.vn:
            quest_generation_enabled = award_generation_enabled = False
            can_damage_npcs = npcs_can_damage_protagonist = False
            scripts_generation_enabled = False

        llm = _world_generator_llm(user, provider, model)
        provider, model = llm.provider, llm.model
        tts_settings = user.tts_settings or {}
        available_voice_list = (
            tts_settings.get("voice_list") if isinstance(tts_settings, dict) else None
        )

        log_structured_event(
            "adventure.generation.start",
            template_id=template_id,
            title=title,
            provider=provider,
            model=model,
            generate_scene_images=generate_scene_images,
            generate_npc_images=generate_npc_images,
            generate_item_images=generate_item_images,
            context_length=len(original_prompt or ""),
            has_cover_source=bool(cover_source_adventure_id),
            cover_similarity_percent=max(0, min(100, int(cover_similarity_percent or 0))),
            allow_reuse_source_assets=bool(allow_reuse_source_assets),
        )

        if not sequences and original_prompt:
            cleaned_prompt, extracted_seqs = WorldGenerator._extract_sequences_from_prompt(
                original_prompt
            )
            if extracted_seqs:
                sequences = extracted_seqs
                original_prompt = cleaned_prompt

        system_prompt, user_prompt = build_world_generation_prompts(
            rule_enforcement_mode=effective_mode,
            title=title,
            original_prompt=original_prompt,
            sequences=sequences,
            generation_strictness=generation_strictness,
            language=language,
            selected_tone=selected_tone,
            automatic_npc_voice_assignment=automatic_npc_voice_assignment,
            available_voice_list=available_voice_list,
            can_damage_npcs=can_damage_npcs,
            npcs_can_damage_protagonist=npcs_can_damage_protagonist,
            quest_generation_enabled=quest_generation_enabled,
            min_scenes=min_scenes,
            max_scenes=max_scenes,
            min_sequences=min_sequences,
            max_sequences=max_sequences,
            min_quests=min_quests,
            max_quests=max_quests,
            award_generation_enabled=award_generation_enabled,
            min_awards=min_awards,
            max_awards=max_awards,
            container_generation_enabled=container_generation_enabled,
            scripts_generation_enabled=scripts_generation_enabled,
            min_containers=min_containers,
            max_containers=max_containers,
            text_log_generation_enabled=text_log_generation_enabled,
            min_text_logs=min_text_logs,
            max_text_logs=max_text_logs,
            min_items=min_items,
            max_items=max_items,
            cover_source_manifest=cover_source_manifest,
            cover_source_adventure_name=cover_source_adventure_name,
            cover_similarity_percent=cover_similarity_percent,
            allow_reuse_source_assets=allow_reuse_source_assets,
        )

        system_prompt += generation_instruction(
            getattr(adventure, "original_manifest", None), mode=effective_mode
        )

        from backend.engine.staged_world import generate_manifest

        async def publish_stage(message: str) -> None:
            await _publish_generation_status_with_callback(
                db, adventure, message, status_callback=status_callback
            )

        manifesto = await generate_manifest(
            db=db,
            adventure=adventure,
            llm=llm,
            status=publish_stage,
            mode=effective_mode,
            template_id=template_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata={
                "generate_scene_images": generate_scene_images,
                "generate_npc_images": generate_npc_images,
                "generate_item_images": generate_item_images,
                "automatic_npc_voice_assignment": automatic_npc_voice_assignment,
                "min_scenes": min_scenes,
                "max_scenes": max_scenes,
                "min_items": min_items,
                "max_items": max_items,
                "container_generation_enabled": container_generation_enabled,
                "scripts_generation_enabled": scripts_generation_enabled,
                "min_containers": min_containers,
                "max_containers": max_containers,
                "text_log_generation_enabled": text_log_generation_enabled,
                "min_text_logs": min_text_logs,
                "max_text_logs": max_text_logs,
                "quest_generation_enabled": quest_generation_enabled,
                "min_quests": min_quests,
                "max_quests": max_quests,
                "min_sequences": min_sequences,
                "max_sequences": max_sequences,
                "award_generation_enabled": award_generation_enabled,
                "min_awards": min_awards,
                "max_awards": max_awards,
            },
        )

        manifest_dict = {**manifesto.model_dump(), "format_version": CURRENT_VERSION}
        if policy.vn:
            normalize_vn_generated_manifest(manifest_dict)
        WorldGenerator.preprocess_manifest_object_ids(manifest_dict)

        log_structured_event(
            "adventure.generation.manifest_received",
            template_id=template_id,
            scene_count=len(manifesto.scenes),
            exit_count=len(manifesto.exits),
            npc_count=len(manifesto.npcs),
            object_count=len(manifesto.objects),
        )

        await persist_generated_narrative(
            db, adventure, template_id, manifest_dict, original_prompt, language, status_callback
        )

        cover_source_assets = await load_cover_source_assets(
            db, cover_source_adventure_id, allow_reuse_source_assets
        )

        constrain_generated_objects(
            manifest_dict,
            max_containers,
            max_text_logs,
            scripts_generation_enabled,
            container_generation_enabled,
            text_log_generation_enabled,
        )

        manifest_dict["cover_source_adventure_id"] = cover_source_adventure_id
        manifest_dict["cover_source_adventure_name"] = cover_source_adventure_name
        manifest_dict["cover_similarity_percent"] = max(
            0, min(100, int(cover_similarity_percent or 0))
        )
        manifest_dict["allow_reuse_source_assets"] = bool(allow_reuse_source_assets)
        manifest_dict["scripts_generation_enabled"] = bool(scripts_generation_enabled)

        await apply_manifest(
            db,
            template_id,
            manifest_dict,
            user=user
            if (generate_npc_images or generate_item_images or generate_scene_images)
            else None,
            gen_npc=generate_npc_images,
            gen_items=generate_item_images,
            gen_scenes=generate_scene_images,
            gen_protagonist_image=generate_scene_images,
            selected_image_styles=selected_image_styles,
            source_assets=cover_source_assets,
            status_callback=status_callback,
        )

        log_structured_event(
            "adventure.generation.world_applied",
            template_id=template_id,
            scene_count=len(manifesto.scenes),
            exit_count=len(manifesto.exits),
            npc_count=len(manifesto.npcs),
            object_count=len(manifesto.objects),
        )
        await db.flush()

    @staticmethod
    async def apply_manifest(
        db: AsyncSession,
        template_id: str,
        manifest_dict: dict,
        user: Optional[User] = None,
        gen_npc: bool = False,
        gen_items: bool = False,
        gen_scenes: bool = False,
        gen_protagonist_image: bool = False,
        existing_images: Optional[dict] = None,
        source_assets: Optional[dict[str, Any]] = None,
        selected_image_styles: Optional[list[str]] = None,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """Populate (or re-populate) world entities based on a manifest dictionary.

        Delegates to ``world_manifest_applier.apply_manifest``.
        """
        from backend.engine.world_manifest_applier import apply_manifest  # noqa: PLC0415

        await apply_manifest(
            db=db,
            template_id=template_id,
            manifest_dict=manifest_dict,
            user=user,
            gen_npc=gen_npc,
            gen_items=gen_items,
            gen_scenes=gen_scenes,
            gen_protagonist_image=gen_protagonist_image,
            existing_images=existing_images,
            source_assets=source_assets,
            selected_image_styles=selected_image_styles,
            status_callback=status_callback,
        )


# Convenience alias so module-level attribute access (world_generator.WorldManifesto etc.) works.
preprocess_manifest_object_ids = WorldGenerator.preprocess_manifest_object_ids
