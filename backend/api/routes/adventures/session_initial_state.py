import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldExit, WorldScene

logger = logging.getLogger(__name__)


def resolve_start_datetime(
    manifest: dict[str, Optional[Any]],
    state: Optional[SessionState] = None,
    time_config: Optional[dict] = None,
) -> Optional[str]:
    """Returns a usable ISO datetime string. Prioritizes session-specific state over manifest."""
    if state and state.start_datetime:
        return state.start_datetime

    target_manifest = manifest or {}

    # Merge explicit editor time_config over manifest defaults so in-game
    # start time can be configured from the world editor.
    merged_time_config = dict(time_config or {})
    manifest_time_config = target_manifest.get("time_config")
    if isinstance(manifest_time_config, dict):
        for k, v in manifest_time_config.items():
            merged_time_config.setdefault(k, v)

    time_sys = merged_time_config.get("time_system") or target_manifest.get("time_system")
    if time_sys in ("relative", "units"):
        return None

    for candidate in (
        merged_time_config.get("start_datetime"),
        target_manifest.get("start_datetime"),
    ):
        parsed = _parse_start_datetime(candidate)
        if parsed:
            return parsed
    start_date = merged_time_config.get("start_date") or target_manifest.get("start_date")
    start_time = merged_time_config.get("start_time") or target_manifest.get("start_time")
    parsed = _parse_start_date_and_time(start_date, start_time)
    if parsed:
        return parsed
    return _configured_year_start(merged_time_config)


def _parse_start_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _parse_start_date_and_time(start_date, start_time):
    if not isinstance(start_date, str) or not start_date.strip():
        return None
    time_part = (
        start_time.strip() if isinstance(start_time, str) and start_time.strip() else "08:00"
    )
    try:
        return datetime.fromisoformat(f"{start_date.strip()}T{time_part}").isoformat()
    except ValueError:
        return None


def _configured_year_start(merged_time_config):
    # Build from start_time (e.g. "14:30") + optional start_year_override.
    base_hour, base_minute = 8, 0
    configured_start = merged_time_config.get("start_time")
    if isinstance(configured_start, str) and configured_start.strip():
        try:
            h, m = map(int, configured_start.strip().split(":"))
            base_hour, base_minute = h, m
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid configured start time.")
    year_override = merged_time_config.get("start_year_override")
    if not configured_start and not year_override:
        return None
    try:
        year = int(year_override) if year_override else 2026
        dt = datetime(year=year, month=1, day=1, hour=base_hour, minute=base_minute)
        return dt.isoformat()
    except Exception:
        return None


async def resolve_initial_scene_id(db: AsyncSession, template_id: Optional[str]) -> str:
    """Resolve a stable initial scene for a fresh session.

    Priority:
    1) Explicit scene from template manifest (`start_scene_id`, `scene_id`, `current_scene_id`).
    2) First scene in template manifest order.
    3) Scene with id "START" when present.
    4) Entry scene(s) with no incoming exits (template baseline only).
    5) Lexicographically first available scene id.
    6) Fallback "START" when no scenes exist.
    """
    if not template_id:
        return "START"

    scene_res = await db.execute(
        select(WorldScene.id).where(
            WorldScene.template_id == template_id,
            WorldScene.session_id.is_(None),
        )
    )
    scene_ids = [sid for sid in scene_res.scalars().all() if isinstance(sid, str) and sid]
    if not scene_ids:
        return "START"

    scene_set = set(scene_ids)

    adv_res = await db.execute(
        select(AdventureTemplate.original_manifest).where(AdventureTemplate.id == template_id)
    )
    original_manifest = adv_res.scalar_one_or_none()
    manifest_start = _manifest_initial_scene(original_manifest, scene_set)
    if manifest_start:
        return manifest_start

    if "START" in scene_set:
        return "START"

    exit_res = await db.execute(
        select(WorldExit.from_scene_id, WorldExit.to_scene_id).where(
            WorldExit.template_id == template_id,
            WorldExit.session_id.is_(None),
        )
    )
    incoming_count: dict[str, int] = {sid: 0 for sid in scene_set}
    for from_scene_id, to_scene_id in exit_res.all():
        if from_scene_id in scene_set and to_scene_id in scene_set:
            incoming_count[to_scene_id] = incoming_count.get(to_scene_id, 0) + 1

    entry_scenes = sorted([sid for sid, count in incoming_count.items() if count == 0])
    if entry_scenes:
        return entry_scenes[0]

    return sorted(scene_set)[0]


def _manifest_initial_scene(original_manifest, scene_set):
    if isinstance(original_manifest, dict):
        explicit_start = (
            original_manifest.get("start_scene_id")
            or original_manifest.get("scene_id")
            or original_manifest.get("current_scene_id")
        )
        if isinstance(explicit_start, str):
            normalized_explicit_start = explicit_start.strip()
            if normalized_explicit_start in scene_set:
                return normalized_explicit_start

        manifest_scenes = original_manifest.get("scenes")
        if isinstance(manifest_scenes, list):
            for entry in manifest_scenes:
                if not isinstance(entry, dict):
                    continue
                candidate = entry.get("id")
                if isinstance(candidate, str):
                    normalized_candidate = candidate.strip()
                    if normalized_candidate in scene_set:
                        return normalized_candidate

    return None
