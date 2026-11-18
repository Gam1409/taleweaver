"""Return a bounded final publication acknowledgment to its own NPC next turn."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.kernel import digest
from backend.engine.debug_transcript import is_debug_message
from backend.engine.npc_actions import control
from backend.engine.npc_actions.acknowledgment_contracts import (
    OperationAcknowledgment,
    PublicationAcknowledgment,
)
from backend.engine.npc_actions.preview import operation_identity
from backend.engine.turn_replay.transactions import release_for_model
from backend.models.chat import ChatMessage

if TYPE_CHECKING:
    from backend.engine.chpm.schema import Decision, Observation

_Stamp = tuple[str, str | None, str, str | None, bool]

_OPERANDS = frozenset({"item_id", "recipient_id", "target_id", "destination_scene_id"})
_DISPOSITION = frozenset({"operation_id", "tool", "status", "reason_code"})


def capture(turn: Any, decision: "Decision") -> PublicationAcknowledgment | None:
    """Take feedback only from this actor's complete, actually published host records."""
    settings = turn.initial.settings
    if settings.mode != "live" or not settings.action_tools or decision.status != "delivered":
        return None
    outcomes = control.validated_outcomes(turn)
    if decision.actor_id not in outcomes:
        return None
    draft = turn.action_drafts.get(decision.actor_id)
    if draft is None or not draft.approved or draft.published_results is None:
        raise control.CommandRejectedError("invalid_operation")
    binding = turn_controls.binding(turn.control)
    observed = decision.observation
    if (turn.input_id, binding.input_id, binding.input_revision, binding.input_hash) != (
        observed.message_id,
        observed.message_id,
        observed.revision_id,
        observed.content_hash,
    ) or (
        draft.scope.session_id,
        draft.scope.actor_id,
        draft.scope.input_id,
        draft.scope.input_revision,
        draft.scope.input_hash,
        draft.scope.scene_id,
    ) != (
        observed.session_id,
        decision.actor_id,
        observed.message_id,
        observed.revision_id,
        observed.content_hash,
        observed.scene_id,
    ):
        raise control.CommandRejectedError("invalid_operation")
    captured = turn_controls.binding(draft.scope.control)
    if any(
        getattr(captured, key) != getattr(binding, key)
        for key in ("attempt_id", "input_id", "input_revision", "input_hash")
    ):
        raise control.CommandRejectedError("invalid_operation")
    rows = outcomes[decision.actor_id]
    if rows != draft.published_results:
        raise control.CommandRejectedError("invalid_operation")
    requested = {
        operation_identity(draft.scope, request, draft.start_index + index)[0]: request.model_dump(
            mode="json", include=_OPERANDS, exclude_none=True
        )
        for index, request in enumerate(draft.requests)
    }
    if any(row.get("command_id") not in requested for row in rows):
        raise control.CommandRejectedError("invalid_operation")
    return PublicationAcknowledgment(
        attempt_id=binding.attempt_id,
        operations=tuple(
            OperationAcknowledgment.model_validate(
                {
                    **{key: value for key, value in row.items() if key in _DISPOSITION},
                    # A blocked receipt has no effect operands. Correlate its own
                    # trusted request by identity, never by reply-list position.
                    **requested[row["command_id"]],
                }
            )
            for row in rows
        ),
    )


async def context(
    manager: Any, previous: "Decision | None", observed: "Observation", actor_id: str
) -> dict | None:
    """Validate saved sources before using old results; they grant no current command authority."""
    if not _eligible(manager.game_id, previous, observed, actor_id):
        return None
    messages = await _read_sources(manager, _source_ids(previous))
    return _from_sources(manager.game_id, previous, observed, actor_id, messages)


def _eligible(
    session_id: str, previous: "Decision | None", observed: "Observation", actor_id: str
) -> bool:
    return not (
        previous is None
        or previous.last_publication is None
        or previous.status != "delivered"
        or previous.actor_id != actor_id
        or previous.observation.session_id != observed.session_id
        or observed.session_id != session_id
        or previous.observation.message_id == observed.message_id
        or previous.reply_id is None
        or previous.reply_hash is None
    )


def _source_ids(previous: "Decision | None") -> set[str]:
    if previous is None:
        return set()
    return {key for key in (previous.observation.message_id, previous.reply_id) if key is not None}


async def _read_sources(manager: Any, identifiers: set[str]) -> dict[str, _Stamp]:
    rows = await manager.db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == manager.game_id, ChatMessage.id.in_(identifiers))
        .execution_options(populate_existing=True)
    )
    # Snapshot all anchors before validating any actor: a later actor read must
    # not leave an earlier silent actor's source unchecked across another await.
    return {
        row.id: (
            row.role,
            row.revision_id,
            digest(row.content),
            row.scene_id,
            row.session_id == manager.game_id
            and not is_debug_message(row)
            and (row.npc_journal or {}).get("status") != "incomplete",
        )
        for row in rows
    }


def _from_sources(
    session_id: str,
    previous: "Decision | None",
    observed: "Observation",
    actor_id: str,
    messages: dict[str, _Stamp],
) -> dict | None:
    if (
        previous is None
        or previous.last_publication is None
        or previous.reply_id is None
        or previous.reply_hash is None
        or not _eligible(session_id, previous, observed, actor_id)
    ):
        return None
    source = previous.observation
    if not _matches(
        messages.get(source.message_id),
        "user",
        source.revision_id,
        source.content_hash,
        source.source_scene_id,
    ) or not _matches(
        messages.get(previous.reply_id),
        "assistant",
        previous.reply_revision,
        previous.reply_hash,
        source.scene_id,
    ):
        return None
    return {
        "meaning": "historical_publication_acknowledgment_not_current_state",
        "semantics": (
            "Blocked/skipped_dependency/stale prove no act or obstacle. Attempted proves no "
            "target response. Keep IDs/codes private. Judge progress from current owner observations. "
            "Choose your next step; others choose theirs."
        ),
        "source_input_id": source.message_id,
        "source_reply_id": previous.reply_id,
        **previous.last_publication.model_dump(mode="json", exclude_none=True),
    }


async def ensure_current(manager: Any, turn: Any) -> None:
    """A silent actor's prior reply may not be among the mind's transcript sources."""
    if await validate_current(manager, turn):
        await release_for_model(manager)


async def validate_current(manager: Any, turn: Any) -> bool:
    """Validate the consumed cohort without releasing or committing its transaction."""
    pending = [
        (actor, turn.initial.actors.get(actor), turn.decisions[actor].observation, supplied)
        for actor, supplied in getattr(turn, "publication_feedback", {}).items()
        if actor in turn.decisions
    ]
    if not pending:
        return False
    messages = await _read_sources(
        manager, {key for _, previous, _, _ in pending for key in _source_ids(previous)}
    )
    for actor, previous, observed, supplied in pending:
        if _from_sources(manager.game_id, previous, observed, actor, messages) != supplied:
            raise StaleControlError(
                "The prior command acknowledgment source changed during this turn."
            )
    return True


def _matches(
    row: _Stamp | None, role: str, revision: str | None, content_hash: str, scene: str | None
) -> bool:
    return row == (role, revision, content_hash, scene, True)
