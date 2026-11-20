"""Carry existing saved-message provenance through the wardrobe owner's plan."""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from backend.core.text_evidence import unique_span
from backend.engine import turn_controls
from backend.engine.clothing.body_schema import WearSource
from backend.engine.clothing.wear_provenance import source_matches
from backend.engine.debug_transcript import is_debug_message
from backend.engine.npc_actions import source_control
from backend.engine.visual_novel.movement_sources import Source
from backend.models.chat import ChatMessage

PHASE = "preliminary_player_wardrobe"


def _source(message: Any, session_id: str, scene_id: str, role: str) -> Source | None:
    if (
        message is None
        or message.session_id != session_id
        or message.scene_id != scene_id
        or message.role != role
        or is_debug_message(message)
        or (message.npc_journal or {}).get("status") == "incomplete"
    ):
        return None
    return Source(
        message.id,
        message.revision_id,
        sha256(message.content.encode()).hexdigest(),
        scene_id,
        role,
        message.content,
        {},
    )


@dataclass(frozen=True)
class PlanSources:
    """A missing current input is invalid; legacy plans omit this capture entirely."""

    current_input: Source | None
    narration: Source | None
    control: dict | None
    narration_control: source_control.Snapshot = field(default_factory=source_control.Snapshot)

    def selected(self, change: Any) -> Source | None:
        return {
            "player_action": self.current_input,
            "completed_narration": self.narration,
        }.get(change.source)

    def wear_source(self, change: Any) -> WearSource | None:
        source = self.selected(change)
        if source is None:
            return None
        proof = WearSource(
            request_id=self.current_input.message_id if self.current_input else None,
            source_message_id=source.message_id,
            source_role="user" if source.role == "user" else "assistant",
            content_hash=source.content_hash,
            evidence=change.evidence,
            evidence_span=unique_span(source.text, change.evidence, None),
        )
        if not source_matches(proof.model_dump(), source.text):
            raise ValueError("The clothing evidence no longer matches its saved source.")
        return proof


@dataclass(frozen=True)
class SourceValidation:
    current_input: bool
    narration: bool

    def admits(self, plan: Any, change: Any, creation_index: int | None = None) -> bool:
        dependent = (
            change.source == "completed_narration" or creation_index in plan.narrated_gift_indices
        )
        return self.current_input and (not dependent or self.narration)


def _narration(
    manager: Any, identifier: str | None, previous: Any
) -> tuple[Source | None, source_control.Snapshot]:
    selected = _source(
        previous, manager.state.session_id, manager.state.current_scene_id, "assistant"
    )
    authority = source_control.read(previous)
    if getattr(manager, "_vn_movement_input", None) != identifier:
        return selected, authority
    prepared = getattr(manager, "_vn_movement_sources", {}).get("previous_narration")
    if (
        not isinstance(prepared, Source)
        or selected is None
        or prepared.message_id != selected.message_id
    ):
        return None, authority
    # Reuse the source offered before inference instead of rebinding an old
    # quote to freshly edited narration or downgraded authority metadata.
    return prepared, getattr(prepared, "command_control", None) or authority


async def capture(manager: Any, user_msg: str, previous: Any) -> PlanSources:
    identifier = getattr(manager, "_vn_player_message_id", None)
    session_id, scene_id = manager.state.session_id, manager.state.current_scene_id
    narration, authority = _narration(manager, identifier, previous)
    attempt = getattr(manager, "_turn_control_attempt", None)
    control = (
        turn_controls.scope(manager, PHASE) if isinstance(attempt, turn_controls.Attempt) else None
    )
    request = (
        await manager.db.get(ChatMessage, identifier, populate_existing=True)
        if identifier
        else None
    )
    current = _source(request, session_id, scene_id, "user")
    if current is not None and current.text != user_msg:
        current = None
    if (
        request
        and previous
        and (previous.created_at, previous.id)
        >= (
            request.created_at,
            request.id,
        )
    ):
        narration = None
    if (
        current is not None
        and control is not None
        and not turn_controls.bind_current(manager, control, PHASE, observation=current)
    ):
        current = None
    return PlanSources(current, narration, control, authority)


async def current(manager: Any, plan: Any) -> SourceValidation:
    """Read each source once; stale history cannot discard independent current effects."""
    sources = plan.sources
    if sources is None:
        return SourceValidation(True, True)
    request = sources.current_input
    if request is None or plan.message_id != request.message_id:
        return SourceValidation(False, False)
    message = await manager.db.get(ChatMessage, request.message_id, populate_existing=True)
    if not request.matches(message, manager.state.session_id):
        return SourceValidation(False, False)
    narration_valid = True
    changes = [*plan.actions, *plan.creations]
    if any(change.source == "completed_narration" for change in changes) or plan.requires_narration:
        narration_valid = await _narration_current(manager, sources)
    # A same-session edit may update the loaded input during the history await.
    current_valid = bool(
        request.matches(message, manager.state.session_id)
        and manager.state.current_scene_id == plan.scene_id
        and getattr(manager, "_vn_player_message_id", None) == request.message_id
        and (sources.control is None or turn_controls.bind_current(manager, sources.control, PHASE))
    )
    return SourceValidation(current_valid, narration_valid)


async def _narration_current(manager: Any, sources: PlanSources) -> bool:
    source = sources.narration
    if source is None or not sources.narration_control.valid:
        return False
    message = await manager.db.get(ChatMessage, source.message_id, populate_existing=True)
    return bool(
        source.matches(message, manager.state.session_id)
        and source_control.read(message) == sources.narration_control
    )
