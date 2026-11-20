"""Admit source-bound external pose proposals through the existing staging owner.

Source binding proves provenance, not arbitrary physics. The existing extractor
still classifies whether a consequence occurred; an interaction receipt certifies
only its performer's attempt, never automatic success against the target.
"""

from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any

from backend.core.text_passages import spans
from backend.engine import turn_controls
from backend.engine.npc_actions.reconciliation import context as command_context
from backend.engine.scene_staging.bindings import bind_retained_objects
from backend.engine.scene_staging.schema import SceneDelta, SceneExtraction
from backend.engine.scene_staging.state import project, retained
from backend.engine.visual_novel import movement_sources

MAX_OPERATION_SOURCES = 16
INSTRUCTIONS = """
EXTERNAL POSE SOURCES: command_controlled_actor_ids own their voluntary pose and
placement through their action API, including an empty plan. Do not add their
unsubmitted self-action through staging. Existing unchanged facts need no new action.
A NEW externally caused change names performer_id separately from entity_id and
cause with basis=resolved_external_effect. For the player's actual performed effect,
use kind=current_player_action and a supplied player:pN passage_id; operation_id=null.
Player source cues/offsets refer to player_report. A request, intention or attempt
is not a resolved consequence. For another NPC use kind=actor_operation with its
supplied operation_id and passage_id=null. That operation proves only the performer's
attempt; the separate current-narration evidence must establish this resolved pose
consequence. Never infer target success from the operation alone. A nonself actor,
room ID or unrelated operation is not a cause. Leave unsupported/unknown causes out,
including unproved world effects. Existing direct canonical effects remain valid.
Keep the performed action, resulting posture and spatial relation distinct. A source
passage may contain several actors; attribute this consequence to its real performer.
"""


@dataclass(frozen=True)
class Scope:
    control: dict
    scene_id: str
    controlled: frozenset[str]
    player: movement_sources.Source | None
    operations: tuple[str, ...]
    omitted_operations: int = 0
    valid: bool = True


def _operations(manager: Any) -> dict[str, dict]:
    context = command_context(manager)
    return {
        row["operation_id"]: row
        for records in (context or {}).get("outcomes", {}).values()
        for row in records
        if row.get("tool") == "interact"
        and row.get("status") == "attempted"
        and isinstance(row.get("effect"), dict)
    }


def _current(manager: Any, scope: Scope) -> bool:
    return scope.scene_id == manager.state.current_scene_id and turn_controls.bind_current(
        manager, scope.control
    )


def _bound_player(player: movement_sources.Source, binding: dict, scene_id: str) -> bool:
    return (player.message_id, player.revision_id, player.content_hash, player.scene_id) == (
        binding["input_id"],
        binding.get("input_revision"),
        binding["input_hash"],
        scene_id,
    )


async def capture(manager: Any) -> Scope | None:
    controlled = command_context(manager)
    if not controlled:
        return None
    binding = turn_controls.scope(manager, "scene_staging")
    source = getattr(manager, "_vn_movement_sources", {}).get("current_player_action")
    player = None
    if isinstance(source, movement_sources.Source):
        with suppress(ValueError):
            player = await movement_sources.current_input(manager, source.text)
    operations = tuple(_operations(manager))
    scope = Scope(
        binding,
        manager.state.current_scene_id,
        frozenset(controlled["controlled_actor_ids"]),
        player,
        operations[-MAX_OPERATION_SOURCES:],
        max(0, len(operations) - MAX_OPERATION_SOURCES),
    )
    return replace(
        scope,
        valid=_current(manager, scope)
        and (
            not isinstance(source, movement_sources.Source)
            or player is not None
            and _bound_player(player, binding, scope.scene_id)
        ),
    )


async def refresh(manager: Any, scope: Scope | None) -> Scope | None:
    if scope is None:
        return None
    if not _current(manager, scope):
        return replace(scope, valid=False)
    if scope.player is None:
        return scope
    try:
        current = await movement_sources.current_input(manager, scope.player.text)
    except ValueError:
        return replace(scope, valid=False)
    return replace(scope, valid=current == scope.player and _current(manager, scope))


def context(
    manager: Any, scope: Scope | None, *, player_text_ref: str | None = "/player_report"
) -> dict:
    if scope is None:
        return {}
    player = scope.player
    sources: dict[str, Any] = {
        "actor_operations": [
            {
                "operation_id": row["operation_id"],
                "performer_id": row["actor_id"],
                "target_id": row["effect"].get("target_id"),
                "status": "attempted",
            }
            for identifier, row in _operations(manager).items()
            if identifier in scope.operations
        ],
        "omitted_actor_operations": scope.omitted_operations,
    }
    if player is not None:
        sources["current_player_action"] = {
            "performer_id": "__player__",
            "source_message_id": player.message_id,
            **({"text_ref": player_text_ref} if player_text_ref else {}),
            "passages": {
                key: {"start": passage.start, "end": passage.end, "cue": passage.text[:64]}
                if player_text_ref
                else {"text": passage.text}
                for key, passage in player.passages.items()
            },
            "omitted_passages": len(spans(player.text)) - len(player.passages),
        }
    return {
        "command_controlled_actor_ids": sorted(scope.controlled),
        "external_pose_sources": sources,
    }


def _new_fields(change: SceneDelta, current: dict) -> set[str]:
    final = {} if change.clear else dict(current)
    if change.posture is not None:
        if change.posture != final.get("posture"):
            final.pop("placement", None)
        final.pop("posture", None)
        if change.posture != "unknown":
            final["posture"] = change.posture
    placement = change.placement
    if placement is not None:
        final.pop("placement", None)
        if placement.relation != "unknown":
            final["placement"] = placement.model_dump()
    return {name for name in ("posture", "placement") if final.get(name) != current.get(name)}


def _source(manager: Any, scope: Scope, change: SceneDelta, known: set[str]) -> dict | None:
    performer, cause = change.performer_id, change.cause
    if (
        performer is None
        or performer == change.entity_id
        or performer not in known
        or cause is None
        or cause.basis != "resolved_external_effect"
    ):
        return None
    if cause.kind == "current_player_action":
        player = scope.player
        if (
            performer != manager.avatar.id
            or player is None
            or cause.operation_id is not None
            or cause.passage_id not in player.passages
        ):
            return None
        return {
            "kind": cause.kind,
            "performer_id": performer,
            "source_message_id": player.message_id,
            "source_revision_id": player.revision_id,
            "source_hash": player.content_hash,
            "passage_id": cause.passage_id,
        }
    row = _operations(manager).get(cause.operation_id or "")
    if (
        cause.passage_id is not None
        or cause.operation_id not in scope.operations
        or row is None
        or row["actor_id"] != performer
        or row["effect"].get("target_id")
        not in {
            change.entity_id,
            "@player" if change.entity_id == manager.avatar.id else change.entity_id,
        }
    ):
        return None
    return {
        "kind": cause.kind,
        "performer_id": performer,
        "source_message_id": row["input_id"],
        "source_revision_id": row.get("input_revision"),
        "source_hash": row["input_hash"],
        "operation_id": row["operation_id"],
    }


def admit(
    manager: Any,
    extraction: SceneExtraction,
    cast: list[dict],
    narration: str,
    scope: Scope | None,
    *,
    scene_objects: dict[str, str | None],
    offered_objects: frozenset[str] | None,
) -> tuple[SceneExtraction, dict, dict, list[dict]]:
    # Compare actor authority only after preview and publication bind the same room identity.
    bind_retained_objects(
        extraction, retained(manager.state, cast, scene_objects), scene_objects, offered_objects
    )
    control = command_context(manager)
    controlled = (
        scope.controlled
        if scope is not None
        else frozenset((control or {}).get("controlled_actor_ids", ()))
    )
    if not controlled:
        return extraction, {}, {}, []
    current = project(manager.state, cast, scene_objects=scene_objects, target_ids=True)
    known = {row["id"] for row in cast}
    selected, sources, external, rejected = [], {}, {}, []
    for change in extraction.changes:
        fields = _new_fields(change, current.get(change.entity_id, {}))
        if change.entity_id not in controlled:
            selected.append(change)
            continue
        if not fields:
            continue  # A source-free echo must not replace the existing owner's proof.
        source = (
            _source(manager, scope, change, known)
            if scope is not None
            and scope.valid
            and _current(manager, scope)
            and change.evidence_span is not None
            and change.evidence_span.matches(narration, change.evidence)
            else None
        )
        if source is None:
            rejected.append(
                {
                    "actor_id": change.entity_id,
                    "fields": sorted(fields),
                    "reason_code": "unconfirmed_pose_performer_or_cause",
                }
            )
            continue
        selected.append(change)
        sources[change.entity_id] = source
        external[change.entity_id] = fields
    return extraction.model_copy(update={"changes": selected}), sources, external, rejected
