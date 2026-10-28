import glob
import logging
import os
import shutil
import time
from copy import deepcopy
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures import legacy_session_mutations
from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.schemas import GameSessionResponse
from backend.core.auth import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.engine.adventure_updates import is_legacy_session
from backend.engine.item_logic import normalize_equipment_keys
from backend.engine.memory_rag.lifecycle import (
    copy_session_summaries,
    memory_snapshot,
    purge_session_memory,
    restore_memory,
)
from backend.engine.npc_journal.messages import copy_messages
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_importer import SessionImporter
from backend.engine.visual_novel.lifecycle import copy_vn_state
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_map import WorldMap
from backend.schemas.checkpoint import RestoreCheckpointResponse, SessionCheckpointResponse
from backend.schemas.session import GameSessionUpdate
from backend.utils.path_security import (
    ensure_within_data_dir as ensure_within_data_dir_shared,
)
from backend.utils.path_security import (
    sanitize_path_component as sanitize_path_component_shared,
)
from backend.utils.text_utils import generate_session_id

router = APIRouter(tags=["Sessions"])
logger = logging.getLogger(__name__)

ITEM_INTEGRITY_FIELDS = [
    "stat_modifier_strength",
    "stat_modifier_dexterity",
    "stat_modifier_intelligence",
    "stat_modifier_wisdom",
    "stat_modifier_charisma",
    "stat_modifier_armor_class",
    "hp_change",
    "stamina_change",
    "mana_change",
]

_SAFE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}


def _is_svg_file(file_path: str, ext: str = "") -> bool:
    """Check if file is an SVG by extension or header sniffing."""
    if ext.lower() == ".svg" or file_path.lower().endswith(".svg"):
        return True
    if not os.path.isfile(file_path):
        return False
    try:
        with open(file_path, "rb") as f:
            return b"<svg" in f.read(512).lower()
    except OSError:
        return False


def _normalize_data_asset_url(source_url: Optional[str]) -> Optional[str]:
    """Normalize legacy relative asset URLs to the canonical /data/... form."""
    if not isinstance(source_url, str):
        return source_url

    candidate = source_url.strip()
    if not candidate:
        return candidate

    lowered = candidate.lower()
    if lowered.startswith(("http://", "https://", "data:", "blob:")):
        return candidate
    if candidate.startswith("/data/"):
        return candidate
    if candidate.startswith("/"):
        return f"/data{candidate}"
    return f"/data/{candidate.lstrip('/')}"


def _sanitize_path_component(value: Optional[str]) -> Optional[str]:
    return sanitize_path_component_shared(value)


def _ensure_within_data_dir(path: str) -> str:
    return ensure_within_data_dir_shared(path)


def _find_existing_data_asset_path(filename: str) -> Optional[str]:
    if not filename:
        return None

    search_roots = [
        _ensure_within_data_dir(os.path.join(settings.DATA_DIR, "adventures", "library")),
        _ensure_within_data_dir(os.path.join(settings.DATA_DIR, "adventures", "sessions")),
    ]

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        pattern = os.path.join(root, "**", filename)
        for candidate in glob.iglob(pattern, recursive=True):
            try:
                resolved = _ensure_within_data_dir(candidate)
            except ValueError:
                continue
            if os.path.isfile(resolved):
                return resolved
    return None


def _cleanup_stale_empty_session_dirs(active_session_ids: set[str], max_age_days: int) -> int:
    """Remove orphaned empty session directories older than max_age_days."""
    if max_age_days <= 0:
        return 0

    sessions_root = _ensure_within_data_dir(
        os.path.join(settings.DATA_DIR, "adventures", "sessions")
    )
    if not os.path.isdir(sessions_root):
        return 0

    cutoff_ts = time.time() - (max_age_days * 24 * 60 * 60)
    removed = 0

    try:
        entries = os.listdir(sessions_root)
    except OSError:
        logger.exception("Failed to list session directory root for stale cleanup.")
        return 0

    for entry in entries:
        safe_id = _sanitize_path_component(entry)
        if not safe_id or safe_id in active_session_ids:
            continue

        candidate = _ensure_within_data_dir(os.path.join(sessions_root, safe_id))
        if not os.path.isdir(candidate):
            continue

        try:
            if os.listdir(candidate):
                continue
            if os.path.getmtime(candidate) >= cutoff_ts:
                continue
            os.rmdir(candidate)
            removed += 1
        except OSError:
            # Ignore race conditions and permission errors; cleanup is best-effort.
            continue

    return removed


def _copy_data_asset_to_session(
    session_id: str,
    bucket: str,
    source_url: Optional[str],
    cache: dict[str, str],
) -> Optional[str]:
    """Copy /data assets into the concrete session folder and return a rewritten URL."""
    normalized_source_url = _normalize_data_asset_url(source_url)
    if not isinstance(normalized_source_url, str) or not normalized_source_url.startswith("/data/"):
        return source_url

    cached = cache.get(normalized_source_url)
    if cached:
        return cached

    from .session_asset_copy import copy_uncached_session_asset

    return copy_uncached_session_asset(session_id, bucket, source_url, normalized_source_url, cache)


def _rewrite_avatar_item_visual_urls(
    avatar: Avatar, session_id: str, cache: dict[str, str]
) -> None:
    """Rewrite avatar inventory/equipment image URLs to copied session-local assets."""
    rewritten_inventory = []
    for item in avatar.inventory or []:
        if isinstance(item, dict):
            item_copy = dict(item)
            item_copy["image_url"] = _copy_data_asset_to_session(
                session_id,
                "items",
                item_copy.get("image_url"),
                cache,
            )
            rewritten_inventory.append(item_copy)
        else:
            rewritten_inventory.append(item)
    avatar.inventory = rewritten_inventory

    rewritten_equipment = {}
    normalized_equipment = normalize_equipment_keys(avatar.equipment)
    for slot, item in normalized_equipment.items():
        if isinstance(item, dict):
            item_copy = dict(item)
            item_copy["image_url"] = _copy_data_asset_to_session(
                session_id,
                "items",
                item_copy.get("image_url"),
                cache,
            )
            rewritten_equipment[slot] = item_copy
        else:
            rewritten_equipment[slot] = item
    avatar.equipment = rewritten_equipment


def _rewrite_asset_snapshot_urls(
    session_id: str, snapshot: dict[str, Any], cache: dict[str, str]
) -> dict[str, Any]:
    """Rewrite known asset snapshot URL fields to copied session-local assets."""
    rewritten = dict(snapshot or {})

    rewritten["cover"] = _copy_data_asset_to_session(
        session_id, "cover", rewritten.get("cover"), cache
    )
    rewritten["protagonist"] = _copy_data_asset_to_session(
        session_id, "protagonist", rewritten.get("protagonist"), cache
    )

    entity_images = rewritten.get("entity_images")
    if isinstance(entity_images, dict):
        rewritten_entity_images = {}
        for ent_id, image_url in entity_images.items():
            rewritten_entity_images[ent_id] = _copy_data_asset_to_session(
                session_id, "entities", image_url, cache
            )
        rewritten["entity_images"] = rewritten_entity_images

    for key, value in list(rewritten.items()):
        if key in {"cover", "protagonist", "entity_images"}:
            continue
        if isinstance(value, str):
            rewritten[key] = _copy_data_asset_to_session(session_id, "snapshot", value, cache)

    return rewritten


def _to_int_or_none(value):
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _backfill_item_from_entity(item: dict, entity: WorldEntity) -> dict:
    merged = dict(item)
    metadata = entity.metadata_json or {}
    item_type = str(entity.item_type or merged.get("item_type") or "").upper()

    # Preserve metadata for item-specific frontend behavior (e.g. READABLE text logs, container locks).
    if isinstance(merged.get("metadata_json"), dict):
        merged_metadata = dict(merged.get("metadata_json") or {})
        for key, value in metadata.items():
            merged_metadata.setdefault(key, value)
        merged["metadata_json"] = merged_metadata
    else:
        merged["metadata_json"] = dict(metadata)

    def fill(key: str, *candidates):
        if merged.get(key) is not None:
            return
        for candidate in candidates:
            val = _to_int_or_none(candidate)
            if val is not None:
                merged[key] = val
                return

    fill(
        "stat_modifier_strength",
        entity.stat_modifier_strength,
        metadata.get("stat_modifier_strength"),
    )
    fill(
        "stat_modifier_dexterity",
        entity.stat_modifier_dexterity,
        metadata.get("stat_modifier_dexterity"),
        metadata.get("stat_modifier_agility"),
    )
    fill(
        "stat_modifier_intelligence",
        entity.stat_modifier_intelligence,
        metadata.get("stat_modifier_intelligence"),
    )
    fill("stat_modifier_wisdom", entity.stat_modifier_wisdom, metadata.get("stat_modifier_wisdom"))
    fill(
        "stat_modifier_charisma",
        entity.stat_modifier_charisma,
        metadata.get("stat_modifier_charisma"),
    )
    fill(
        "stat_modifier_armor_class",
        entity.stat_modifier_armor_class,
        metadata.get("stat_modifier_armor_class"),
    )

    effects = metadata.get("effects") if isinstance(metadata.get("effects"), dict) else {}
    fill(
        "hp_change",
        metadata.get("hp_change"),
        metadata.get("health_change"),
        effects.get("hp"),
        effects.get("health"),
    )
    fill(
        "stamina_change",
        metadata.get("stamina_change"),
        effects.get("stamina"),
        effects.get("energy"),
    )
    fill("mana_change", metadata.get("mana_change"), effects.get("mana"))

    if item_type == "READABLE":
        _backfill_readable_fields(merged, metadata)

    return merged


def _reconstruct_item_dict_from_entity(entity: WorldEntity) -> dict:
    from backend.engine.item_logic import get_item_slot

    guessed_slot = get_item_slot(entity.name, entity.item_type or "PICKABLE")
    slots = entity.wearable_slots
    if isinstance(slots, list) and len(slots) > 0:
        item_slot = slots[0]
    elif isinstance(slots, str):
        item_slot = slots
    else:
        item_slot = guessed_slot

    metadata = entity.metadata_json or {}
    effects = metadata.get("effects") if isinstance(metadata.get("effects"), dict) else {}
    item_type = entity.item_type or "PICKABLE"

    text_log_content = str(metadata.get("text_log_content") or "").strip()[:1000]
    text_log_format = str(metadata.get("text_log_format") or "DOCUMENT").strip().upper()
    if text_log_format not in {"DOCUMENT", "SCROLL", "BOOK", "SIGN"}:
        text_log_format = "DOCUMENT"

    def get_val(*candidates):
        for candidate in candidates:
            val = _to_int_or_none(candidate)
            if val is not None:
                return val
        return None

    return {
        "id": entity.id,
        "name": entity.name,
        "description": entity.description,
        "image_url": entity.image_url,
        "item_type": item_type,
        "slot": item_slot,
        "metadata_json": dict(metadata),
        "text_log_content": text_log_content if str(item_type).upper() == "READABLE" else "",
        "text_log_format": text_log_format if str(item_type).upper() == "READABLE" else "",
        "stat_modifier_strength": get_val(
            entity.stat_modifier_strength, metadata.get("stat_modifier_strength")
        ),
        "stat_modifier_dexterity": get_val(
            entity.stat_modifier_dexterity,
            metadata.get("stat_modifier_dexterity"),
            metadata.get("stat_modifier_agility"),
        ),
        "stat_modifier_intelligence": get_val(
            entity.stat_modifier_intelligence, metadata.get("stat_modifier_intelligence")
        ),
        "stat_modifier_wisdom": get_val(
            entity.stat_modifier_wisdom, metadata.get("stat_modifier_wisdom")
        ),
        "stat_modifier_charisma": get_val(
            entity.stat_modifier_charisma, metadata.get("stat_modifier_charisma")
        ),
        "stat_modifier_armor_class": get_val(
            entity.stat_modifier_armor_class, metadata.get("stat_modifier_armor_class")
        ),
        "hp_change": get_val(
            metadata.get("hp_change"),
            metadata.get("health_change"),
            effects.get("hp"),
            effects.get("health"),
        ),
        "stamina_change": get_val(
            metadata.get("stamina_change"), effects.get("stamina"), effects.get("energy")
        ),
        "mana_change": get_val(metadata.get("mana_change"), effects.get("mana")),
    }


def _backfill_avatar_items_from_template_entities(
    avatar: Avatar, entities_by_id: dict[str, WorldEntity]
) -> None:
    inventory = []
    for item in avatar.inventory or []:
        if isinstance(item, str) and item in entities_by_id:
            inventory.append(_reconstruct_item_dict_from_entity(entities_by_id[item]))
        elif isinstance(item, dict) and item.get("id") in entities_by_id:
            inventory.append(_backfill_item_from_entity(item, entities_by_id[item["id"]]))
        else:
            inventory.append(item)
    avatar.inventory = inventory

    equipment = {}
    normalized_equipment = normalize_equipment_keys(avatar.equipment)
    for slot, item in normalized_equipment.items():
        if isinstance(item, str) and item in entities_by_id:
            equipment[slot] = _reconstruct_item_dict_from_entity(entities_by_id[item])
        elif isinstance(item, dict) and item.get("id") in entities_by_id:
            equipment[slot] = _backfill_item_from_entity(item, entities_by_id[item["id"]])
        else:
            equipment[slot] = item
    avatar.equipment = equipment


def _iter_avatar_items(avatar: Avatar):
    for index, item in enumerate(avatar.inventory or []):
        if isinstance(item, dict):
            yield (f"inventory[{index}]", item)

    for slot, item in (avatar.equipment or {}).items():
        if isinstance(item, dict):
            yield (f"equipment.{slot}", item)


async def _resolve_session_asset(
    state: SessionState, key: str, fallback: Optional[str] = None
) -> Optional[str]:
    # Placeholder or import from logic if needed
    return AdventureLogic.resolve_session_asset(state, key, fallback)


@router.get("/sessions", response_model=list[GameSessionResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """Returns all game sessions for the current user."""
    all_session_ids_res = await db.execute(select(GameSession.id))
    all_session_ids = {sid for sid in all_session_ids_res.scalars().all() if isinstance(sid, str)}
    removed_dirs = _cleanup_stale_empty_session_dirs(
        active_session_ids=all_session_ids,
        max_age_days=max(0, int(getattr(settings, "SESSION_EMPTY_DIR_CLEANUP_DAYS", 7))),
    )
    if removed_dirs:
        logger.info("Removed %s stale empty session directories.", removed_dirs)

    result = await db.execute(
        select(GameSession, SessionState, AdventureTemplate, WorldScene.label, Avatar.profile_image)
        .outerjoin(SessionState, SessionState.session_id == GameSession.id)
        .outerjoin(AdventureTemplate, GameSession.template_id == AdventureTemplate.id)
        .outerjoin(Avatar, Avatar.id == SessionState.avatar_id)
        .outerjoin(
            WorldScene,
            (WorldScene.id == SessionState.current_scene_id)
            & (WorldScene.session_id == GameSession.id),
        )
        .where(GameSession.user_id == current_user.id)
        .distinct()
    )
    rows = result.all()
    user_earned_awards = current_user.earned_awards or []

    return [
        GameSessionResponse(
            game_id=g.id,
            template_id=g.template_id,
            adventure_id=g.template_id,
            avatar_id=g.avatar_id,
            profile_image=AdventureLogic.resolve_session_asset(
                s, "protagonist", avatar_profile_image
            ),
            adventure_title=a.title if a else (g.adventure_title or "Unknown"),
            adventure_version=a.version
            if a
            else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                "version"
            ),
            image_url=AdventureLogic.resolve_session_asset(
                s, "cover", a.image_url if a else g.adventure_image_url
            ),
            scene_id=s.current_scene_id if s else "START",
            current_scene_name=scene_label or ("Exploring..." if s else "Archived"),
            in_game_time=s.in_game_time if s else 0,
            playtime_seconds=g.playtime_seconds,
            is_ready=a.is_ready if a else True,
            creation_status=a.creation_status if a else "Ready",
            creation_error=a.creation_error if a else None,
            selected_tone=a.selected_tone
            if a
            else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                "selected_tone"
            ),
            progress=AdventureLogic.calculate_quest_progress(
                s.quests if s else (a.quests if a else None)
            ),
            quest_count=len((s.quests if s else (a.quests if a else None)) or []),
            completed_quest_count=len(
                [
                    q
                    for q in ((s.quests if s else (a.quests if a else None)) or [])
                    if q.get("status") == "completed"
                ]
            ),
            award_count=len(
                (
                    a.awards
                    if a
                    else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                        "awards"
                    )
                )
                or []
            ),
            earned_award_count=len(
                [
                    aw
                    for aw in ((a.awards if a else None) or [])
                    if any(
                        ea.get("key") == aw.get("key")
                        and (ea.get("template_id") == a.id or ea.get("adventure_id") == a.id)
                        for ea in user_earned_awards
                    )
                ]
            ),
            created_at=g.created_at,
            status=g.status,
            status_note=g.status_note,
            copied_from_id=g.copied_from_id,
            is_legacy_format=is_legacy_session(session=g, state=s, template=a),
            rule_enforcement_mode=a.rule_enforcement_mode
            if a
            else (
                (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                    "rule_enforcement_mode"
                )
                or "rpg"
            ),
            selected_image_styles=a.selected_image_styles
            if a
            else (
                (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                    "selected_image_styles"
                )
                or (s.selected_image_styles if s else None)
            ),
        )
        for g, s, a, scene_label, avatar_profile_image in rows
    ]


@router.post("/{template_id}/sessions/start", status_code=201)
async def start_session_for_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Creates a new active session for a template and returns its identifiers."""
    adv_res = await db.execute(select(AdventureTemplate).where(AdventureTemplate.id == template_id))
    adventure = adv_res.scalars().first()
    if not adventure:
        raise HTTPException(status_code=404, detail="AdventureTemplate not found.")

    # Allow if user is owner OR if adventure is ready (public-ready)
    if adventure.owner_id != current_user.id and not adventure.is_ready:
        raise HTTPException(status_code=403, detail="You do not have access to this adventure yet.")

    # Disallow starting sessions on legacy/outdated format adventures
    from backend.engine.adventure_updates import (
        check_template_update,
        scan_available_adventure_files,
    )

    files = scan_available_adventure_files()
    update_info = check_template_update(adventure, files)
    if update_info["is_legacy_format"] or not update_info["can_start"]:
        raise HTTPException(
            status_code=400,
            detail="This adventure uses an outdated format and is no longer usable. Please update the adventure first.",
        )

    from .session_start_avatar import resolve_start_avatar

    avatar = await resolve_start_avatar(db, template_id, current_user, adventure)

    # Repair legacy imported avatars: backfill missing item effects/stats from template entities.
    entity_rows = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == template_id,
            WorldEntity.session_id.is_(None),
            WorldEntity.entity_type == "OBJECT",
        )
    )
    entities_by_id = {ent.id: ent for ent in entity_rows.scalars().all() if ent.id}
    if entities_by_id:
        _backfill_avatar_items_from_template_entities(avatar, entities_by_id)

    db.add(avatar)
    await db.flush()

    first_scene_id = await AdventureLogic.resolve_initial_scene_id(db, template_id)

    new_session = GameSession(
        id=generate_session_id(adventure.title or template_id),
        user_id=current_user.id,
        avatar_id=avatar.id,
        template_id=template_id,
        adventure_title=adventure.title,
        adventure_image_url=adventure.image_url,
        status="active",
    )
    db.add(new_session)
    await db.flush()

    # Ensure a concrete session filesystem root exists for session-bound artifacts (e.g. TTS).
    os.makedirs(
        os.path.join(settings.DATA_DIR, "adventures", "sessions", new_session.id), exist_ok=True
    )

    from .session_start_assets import initialize_session_assets

    (
        asset_copy_cache,
        entity_images,
        initial_entity_states,
        template_entities,
    ) = await initialize_session_assets(db, template_id, new_session, avatar, adventure)

    user_llm_settings = getattr(current_user, "llm_settings", None) or {}
    configured_turns = user_llm_settings.get("turns_before_compacting") or user_llm_settings.get(
        "default_max_memory_turns"
    )
    adv_turns = getattr(adventure, "max_memory_turns", None)
    initial_turns = adv_turns if adv_turns is not None else (configured_turns or 10)
    initial_compression = bool(user_llm_settings.get("enable_history_compression", True))

    from .session_start_scripts import run_adventure_initialization

    init_narrative_messages = run_adventure_initialization(
        adventure, template_entities, avatar, first_scene_id, initial_entity_states
    )

    new_state = SessionState(
        session_id=new_session.id,
        user_id=current_user.id,
        template_id=template_id,
        avatar_id=avatar.id,
        current_scene_id=first_scene_id,
        in_game_time=0,
        max_memory_turns=initial_turns or 10,
        enable_history_compression=initial_compression,
        quests=deepcopy(adventure.quests or []),
        entity_states=initial_entity_states,
        time_system=adventure.time_system or "calendar",
        time_config=deepcopy(adventure.time_config) if adventure.time_config else None,
        start_datetime=AdventureLogic.resolve_start_datetime(
            adventure.original_manifest, time_config=adventure.time_config
        ),
        plot=adventure.plot,
        rules=adventure.rules,
        walkthrough=adventure.walkthrough,
        completed_condition=adventure.completed_condition,
        gameover_condition=adventure.gameover_condition,
        completed_guard_expression=adventure.completed_guard_expression,
        gameover_guard_expression=adventure.gameover_guard_expression,
        tts_director_notes=adventure.tts_director_notes,
        selected_image_styles=deepcopy(adventure.selected_image_styles),
        selected_tone=deepcopy(adventure.selected_tone),
    )
    db.add(new_state)

    from .session_start_scripts import add_initial_session_messages

    await add_initial_session_messages(db, adventure, new_session, init_narrative_messages)

    from .session_start_world import clone_template_world

    await clone_template_world(
        db, template_id, new_session, avatar, asset_copy_cache, entity_images
    )

    await db.commit()
    return {"game_id": new_session.id, "template_id": template_id, "avatar_id": avatar.id}


@router.post("/{template_id}/reset")
async def reset_adventure(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await legacy_session_mutations.reset_sessions(db, template_id, current_user.id)


@router.delete("/sessions/{game_id}", status_code=200)
async def delete_session(
    game_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = result.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    avatar_id = game_session.avatar_id
    await purge_session_memory(db, current_user.id, game_id)

    # Explicitly remove session-bound rows that may not be ORM-cascaded.
    await db.execute(delete(SessionCheckpoint).where(SessionCheckpoint.session_id == game_id))
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == game_id))
    await db.execute(delete(SessionState).where(SessionState.session_id == game_id))
    await db.execute(delete(WorldEntity).where(WorldEntity.session_id == game_id))
    await db.execute(delete(WorldScene).where(WorldScene.session_id == game_id))
    await db.execute(delete(WorldExit).where(WorldExit.session_id == game_id))
    await db.execute(delete(WorldMap).where(WorldMap.session_id == game_id))

    await db.delete(game_session)

    # Remove avatar only if no other session references it.
    other_session_res = await db.execute(
        select(GameSession.id)
        .where(GameSession.avatar_id == avatar_id, GameSession.id != game_id)
        .limit(1)
    )
    if not other_session_res.scalar_one_or_none():
        avatar_res = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
        avatar = avatar_res.scalars().first()
        if avatar:
            await db.delete(avatar)

    await db.commit()

    # Remove session-bound files from disk.
    safe_game_id = _sanitize_path_component(str(game_session.id))
    if safe_game_id:
        session_dir = _ensure_within_data_dir(
            os.path.join(settings.DATA_DIR, "adventures", "sessions", safe_game_id)
        )
        if os.path.isdir(session_dir):
            try:
                shutil.rmtree(session_dir)
            except OSError:
                logger.exception("Failed to remove session directory for %s", game_id)
    else:
        logger.warning("Skipping session directory cleanup due to invalid session id: %s", game_id)

    return {"status": "deleted", "game_id": game_id}


@router.delete("/sessions/{game_id}/messages/{message_id}", status_code=200)
async def delete_chat_message(
    game_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes a single chat message from the session history in debug mode."""
    session_res = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = session_res.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    state_res = await db.execute(select(SessionState).where(SessionState.session_id == game_id))
    state = state_res.scalars().first()
    is_debug = settings.TALEWEAVER_DEBUG_ENABLED or (state and state.is_debug_enabled)
    if not is_debug:
        raise HTTPException(status_code=403, detail="Not in debug mode.")

    msg_res = await db.execute(
        select(ChatMessage).where(
            (ChatMessage.id == message_id) & (ChatMessage.session_id == game_id)
        )
    )
    message = msg_res.scalars().first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    await db.delete(message)
    await db.commit()
    return {"status": "deleted", "message_id": message_id}


@router.get("/sessions/{game_id}/integrity/items", status_code=200)
async def check_session_item_integrity(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Checks if session avatar item modifiers/effects match available template object data."""
    session_res = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = session_res.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    avatar_res = await db.execute(select(Avatar).where(Avatar.id == game_session.avatar_id))
    avatar = avatar_res.scalars().first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Session avatar not found.")

    template_entities_res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == game_session.template_id,
            WorldEntity.entity_type == "OBJECT",
        )
    )
    entities_by_id = {ent.id: ent for ent in template_entities_res.scalars().all() if ent.id}

    issues: list[dict[str, Any]] = []
    checked_items = 0

    for location, item in _iter_avatar_items(avatar):
        item_id = item.get("id")
        if not item_id:
            continue
        checked_items += 1

        entity = entities_by_id.get(item_id)
        if not entity:
            continue

        expected = _backfill_item_from_entity(item, entity)
        for field in ITEM_INTEGRITY_FIELDS:
            current_value = item.get(field)
            expected_value = expected.get(field)
            if current_value is None and expected_value is not None:
                issues.append(
                    {
                        "location": location,
                        "item_id": item_id,
                        "item_name": item.get("name") or entity.name,
                        "field": field,
                        "current": current_value,
                        "expected": expected_value,
                    }
                )

    return {
        "status": "ok",
        "game_id": game_id,
        "template_id": game_session.template_id,
        "checked_items": checked_items,
        "issue_count": len(issues),
        "issues": issues,
    }


@router.post("/sessions/{game_id}/copy", status_code=201)
async def copy_session(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Creates a full duplicate/copy of an existing session."""
    # 1. Fetch original session
    session_res = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    original_session = session_res.scalars().first()
    if not original_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # 2. Fetch original avatar
    avatar_res = await db.execute(select(Avatar).where(Avatar.id == original_session.avatar_id))
    original_avatar = avatar_res.scalars().first()
    if not original_avatar:
        raise HTTPException(status_code=404, detail="Session avatar not found.")

    asset_copy_cache: dict[str, str] = {}

    # 3. Clone Avatar
    cloned_avatar = Avatar(
        user_id=current_user.id,
        template_id=original_avatar.template_id,
        name=original_avatar.name,
        role=original_avatar.role,
        description=original_avatar.description,
        goal=original_avatar.goal,
        character=original_avatar.character,
        visual_profile=deepcopy(original_avatar.visual_profile),
        profile_image=original_avatar.profile_image,
        hp=original_avatar.hp,
        max_hp=original_avatar.max_hp,
        stamina=original_avatar.stamina,
        max_stamina=original_avatar.max_stamina,
        mana=original_avatar.mana,
        max_mana=original_avatar.max_mana,
        strength=original_avatar.strength,
        dexterity=original_avatar.dexterity,
        intelligence=original_avatar.intelligence,
        wisdom=original_avatar.wisdom,
        charisma=original_avatar.charisma,
        armor_class=original_avatar.armor_class,
        stats=deepcopy(original_avatar.stats or {}),
        inventory=deepcopy(original_avatar.inventory or []),
        equipment=normalize_equipment_keys(original_avatar.equipment),
        status_effects=deepcopy(original_avatar.status_effects or []),
    )
    db.add(cloned_avatar)
    await db.flush()

    # 4. Create cloned GameSession
    orig_title = original_session.adventure_title or "Unknown Adventure"
    new_title = orig_title if orig_title.startswith("Kopie von ") else f"Kopie von {orig_title}"

    copied_session = GameSession(
        id=generate_session_id(
            original_session.adventure_title or original_session.template_id or "copy"
        ),
        user_id=current_user.id,
        avatar_id=cloned_avatar.id,
        template_id=original_session.template_id,
        adventure_title=new_title,
        adventure_image_url=original_session.adventure_image_url,
        status=original_session.status,
        status_note=original_session.status_note,
        copied_from_id=original_session.id,
        content_language=original_session.content_language,
        playtime_seconds=original_session.playtime_seconds,
    )
    db.add(copied_session)
    await db.flush()

    # Create session-bound folder
    os.makedirs(
        os.path.join(settings.DATA_DIR, "adventures", "sessions", copied_session.id), exist_ok=True
    )

    copied_cover_url = _copy_data_asset_to_session(
        copied_session.id,
        "cover",
        original_session.adventure_image_url,
        asset_copy_cache,
    )
    copied_session.adventure_image_url = copied_cover_url or original_session.adventure_image_url

    copied_profile_url = _copy_data_asset_to_session(
        copied_session.id,
        "protagonist",
        original_avatar.profile_image,
        asset_copy_cache,
    )
    cloned_avatar.profile_image = copied_profile_url or original_avatar.profile_image
    _rewrite_avatar_item_visual_urls(cloned_avatar, copied_session.id, asset_copy_cache)

    from .session_copy_state import clone_saved_session_state

    original_state, cloned_state = await clone_saved_session_state(
        db, original_session, copied_session, current_user, cloned_avatar, asset_copy_cache
    )

    # 6. Clone the conversation and map evidence to its new message IDs.
    message_ids = await copy_messages(db, original_session.id, copied_session.id)
    if original_state:
        restore_memory(cloned_state, memory_snapshot(original_state), message_ids)
        cloned_state.entity_states = copy_vn_state(
            cloned_state.entity_states,
            message_ids,
            lambda url: _copy_data_asset_to_session(
                copied_session.id, "illustrations", url, asset_copy_cache
            ),
        )

    from .session_copy_world import clone_saved_world

    await clone_saved_world(db, original_session, copied_session, asset_copy_cache, message_ids)

    await copy_session_summaries(
        db,
        original_session.id,
        copied_session.id,
        current_user.id,
        message_ids,
    )

    # 10. Clone WorldMap
    map_res = await db.execute(select(WorldMap).where(WorldMap.session_id == original_session.id))
    original_map = map_res.scalars().first()
    if original_map:
        cloned_map = WorldMap(
            template_id=original_map.template_id,
            session_id=copied_session.id,
            nodes=deepcopy(original_map.nodes),
            edges=deepcopy(original_map.edges),
            current_scene_id=original_map.current_scene_id,
        )
        db.add(cloned_map)

    await db.commit()
    return {
        "game_id": copied_session.id,
        "template_id": copied_session.template_id,
        "avatar_id": cloned_avatar.id,
    }


# ---------------------------------------------------------------------------
# /{template_id}/state  (adventure-scoped convenience routes used by the UI)
# ---------------------------------------------------------------------------


@router.get("/{template_id}/state")
async def get_adventure_state(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Returns a lightweight snapshot of the most-recent session state for a template."""
    state_res = await db.execute(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(
            GameSession.template_id == template_id,
            GameSession.user_id == current_user.id,
        )
        .order_by(GameSession.created_at.desc())
        .limit(1)
    )
    state = state_res.scalars().first()
    if not state:
        raise HTTPException(status_code=404, detail="No session found for this adventure.")

    game_session_res = await db.execute(
        select(GameSession).where(GameSession.id == state.session_id)
    )
    game_session = game_session_res.scalars().first()

    return {
        "scene_id": state.current_scene_id,
        "in_game_time": state.in_game_time or 0,
        "is_paused": bool(game_session and game_session.status == "paused"),
        "session_id": state.session_id,
    }


@router.patch("/{template_id}/state")
async def update_adventure_state(
    template_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await legacy_session_mutations.update_state(db, template_id, current_user.id, payload)


@router.post("/{template_id}/pause")
async def pause_adventure(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await legacy_session_mutations.change_status(
        db, template_id, current_user.id, "active", "paused"
    )


@router.post("/{template_id}/resume")
async def resume_adventure(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await legacy_session_mutations.change_status(
        db, template_id, current_user.id, "paused", "active"
    )


async def _get_session_response(
    db: AsyncSession, game_id: str, current_user_id: str
) -> GameSessionResponse:
    # Query single session with joins
    result = await db.execute(
        select(GameSession, SessionState, AdventureTemplate, WorldScene.label, Avatar.profile_image)
        .outerjoin(SessionState, SessionState.session_id == GameSession.id)
        .outerjoin(AdventureTemplate, GameSession.template_id == AdventureTemplate.id)
        .outerjoin(Avatar, Avatar.id == SessionState.avatar_id)
        .outerjoin(
            WorldScene,
            (WorldScene.id == SessionState.current_scene_id)
            & (WorldScene.session_id == GameSession.id),
        )
        .where((GameSession.id == game_id) & (GameSession.user_id == current_user_id))
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found.")

    g, s, a, scene_label, avatar_profile_image = row

    # We can fetch earned awards here
    user_res = await db.execute(select(User).where(User.id == current_user_id))
    current_user = user_res.scalar_one()
    user_earned_awards = current_user.earned_awards or []

    return GameSessionResponse(
        game_id=g.id,
        template_id=g.template_id,
        adventure_id=g.template_id,
        avatar_id=g.avatar_id,
        profile_image=AdventureLogic.resolve_session_asset(s, "protagonist", avatar_profile_image),
        adventure_title=a.title if a else (g.adventure_title or "Unknown"),
        adventure_version=a.version
        if a
        else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get("version"),
        creator=a.creator if a else None,
        copyright=a.copyright if a else None,
        license=a.license if a else None,
        license_url=a.license_url if a else None,
        image_url=AdventureLogic.resolve_session_asset(
            s, "cover", a.image_url if a else g.adventure_image_url
        ),
        scene_id=s.current_scene_id if s else "START",
        current_scene_name=scene_label or ("Exploring..." if s else "Archived"),
        in_game_time=s.in_game_time if s else 0,
        playtime_seconds=g.playtime_seconds,
        is_ready=a.is_ready if a else True,
        creation_status=a.creation_status if a else "Ready",
        creation_error=a.creation_error if a else None,
        selected_tone=a.selected_tone
        if a
        else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
            "selected_tone"
        ),
        progress=AdventureLogic.calculate_quest_progress(
            s.quests if s else (a.quests if a else None)
        ),
        quest_count=len((s.quests if s else (a.quests if a else None)) or []),
        completed_quest_count=len(
            [
                q
                for q in ((s.quests if s else (a.quests if a else None)) or [])
                if q.get("status") == "completed"
            ]
        ),
        award_count=len(
            (
                a.awards
                if a
                else (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                    "awards"
                )
            )
            or []
        ),
        earned_award_count=len(
            [
                aw
                for aw in ((a.awards if a else None) or [])
                if any(
                    ea.get("key") == aw.get("key")
                    and (ea.get("template_id") == a.id or ea.get("adventure_id") == a.id)
                    for ea in user_earned_awards
                )
            ]
        ),
        created_at=g.created_at,
        status=g.status,
        status_note=g.status_note,
        copied_from_id=g.copied_from_id,
        is_legacy_format=is_legacy_session(session=g, state=s, template=a),
        rule_enforcement_mode=a.rule_enforcement_mode
        if a
        else (
            (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                "rule_enforcement_mode"
            )
            or "rpg"
        ),
        selected_image_styles=a.selected_image_styles
        if a
        else (
            (AdventureLogic.extract_manifest_snapshot(s).get("adventure") or {}).get(
                "selected_image_styles"
            )
            or (s.selected_image_styles if s else None)
        ),
        max_memory_turns=getattr(s, "max_memory_turns", 10) if s else 10,
        enable_history_compression=getattr(s, "enable_history_compression", True) if s else True,
    )


@router.patch("/sessions/{game_id}", response_model=GameSessionResponse)
async def update_session(
    game_id: str,
    payload: GameSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = result.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if payload.status is not None:
        game_session.status = payload.status
    if payload.status_note is not None:
        game_session.status_note = payload.status_note
    if payload.max_memory_turns is not None or payload.enable_history_compression is not None:
        state_res = await db.execute(select(SessionState).where(SessionState.session_id == game_id))
        session_state = state_res.scalars().first()
        if session_state:
            if payload.max_memory_turns is not None:
                session_state.max_memory_turns = max(1, min(100, int(payload.max_memory_turns)))
            if payload.enable_history_compression is not None:
                session_state.enable_history_compression = payload.enable_history_compression

    await db.commit()

    return await _get_session_response(db, game_id, current_user.id)


@router.get("/sessions/{game_id}/checkpoints", response_model=list[SessionCheckpointResponse])
async def list_session_checkpoints(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SessionCheckpointResponse]:
    session_res = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = session_res.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    return await SessionCheckpointService.list_checkpoints(db, game_id)


@router.post(
    "/sessions/{game_id}/checkpoints/{checkpoint_id}/restore",
    response_model=RestoreCheckpointResponse,
)
async def restore_session_checkpoint(
    game_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RestoreCheckpointResponse:
    session_res = await db.execute(
        select(GameSession).where(
            (GameSession.id == game_id) & (GameSession.user_id == current_user.id)
        )
    )
    game_session = session_res.scalars().first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        deleted_messages = await SessionCheckpointService.restore_checkpoint(
            db, game_id, checkpoint_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Event-table pruning is intentionally deferred until a dedicated event store exists.
    logger.info(
        "Checkpoint restore for session %s pruned %s chat messages.", game_id, deleted_messages
    )
    await db.commit()

    return RestoreCheckpointResponse(
        status="restored",
        checkpoint_id=checkpoint_id,
        deleted_messages=deleted_messages,
    )


@router.post("/sessions/import")
async def import_session_ads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a game session from a portable .ads (ZIP) file."""
    try:
        content = await file.read()
        new_session_id = await SessionImporter.import_ads(db, content, owner_id=current_user.id)
        if not new_session_id:
            raise HTTPException(
                status_code=400, detail="The ADS file is invalid or could not be processed."
            )
        return {
            "status": "success",
            "game_id": new_session_id,
            "message": "Session imported successfully.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ADS Import failed")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}") from e


def _backfill_readable_fields(merged, metadata):
    if not merged.get("text_log_content"):
        merged["text_log_content"] = str(metadata.get("text_log_content") or "").strip()[:1000]
    if not merged.get("text_log_format"):
        text_log_format = str(metadata.get("text_log_format") or "DOCUMENT").strip().upper()
        if text_log_format not in {"DOCUMENT", "SCROLL", "BOOK", "SIGN"}:
            text_log_format = "DOCUMENT"
        merged["text_log_format"] = text_log_format
