"""Compare two independent, typed readings of a single reviewed public transfer."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any

from backend.core.text_passages import index, spans
from backend.engine import turn_controls
from backend.engine.actor_aliases import canonical_owner, public_actor_id
from backend.engine.chpm import passages, receipt_review
from backend.engine.chpm.errors import StaleControlError
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions import custody_effects, execution_frame
from backend.engine.npc_actions.control import CommandRejectedError, model_outcomes
from backend.engine.visual_novel.continuity import PLAYER, SCENE

_CUSTODY = {"take_item", "give_item", "put_down_item"}
_MAX_ISSUES = 8


def _digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Transfer:
    actor_id: str
    operation_id: str
    tool: str
    item: str
    source: str
    destination: str


@dataclass(frozen=True)
class Citation:
    passage_id: str
    start: int
    end: int
    passage_hash: str
    unique_in_original: bool
    transfer: Transfer


@dataclass(frozen=True)
class Proof:
    publication_scope: str
    review_scope: str
    text_hash: str
    citations: tuple[Citation, ...]
    occurrences: tuple[tuple[str, int, int, str, bool], ...] = ()


@dataclass
class _Public:
    scope: str
    actors: set[str]
    operations: dict[str, Transfer]
    effects: list[dict]
    order: dict[str, int]


def _transfer(row: dict, actors: set[str]) -> Transfer | None:
    tool, actor = row["tool"], row["actor_id"]
    if tool not in _CUSTODY or row["status"] != "applied" or row.get("effect_omitted"):
        return None
    effect = row.get("effect") or {}
    item, src, dst = (
        effect.get("item_id"),
        effect.get("source_owner"),
        effect.get("destination_owner"),
    )
    if (
        not isinstance(item, str)
        or not item
        or not isinstance(src, str)
        or not isinstance(dst, str)
        or src not in actors
        or dst not in actors
        or src == dst
    ):
        return None
    roles = {
        "take_item": (SCENE, actor),
        "put_down_item": (actor, SCENE),
        "give_item": (actor, dst),
    }
    if (src, dst) != roles[tool] or (tool == "give_item" and dst == SCENE):
        return None
    return Transfer(
        actor, row["operation_id"], tool, item, canonical_owner(src), canonical_owner(dst)
    )


def _current_public(turn: Any) -> _Public | None:
    frame = getattr(turn, "execution_frame", None)
    if not isinstance(frame, execution_frame.Frame) or not getattr(turn, "review_operation", None):
        return None
    observed = frame.observation
    if (
        frame.binding != turn.control
        or frame.scene_id != observed.scene_id
        or turn.input_id != observed.message_id
        or (
            frame.binding.get("input_id"),
            frame.binding.get("input_hash"),
            frame.binding.get("input_revision"),
        )
        != (observed.message_id, observed.content_hash, observed.revision_id)
    ):
        return None
    actors = {key for key, row in frame.entities.items() if row.get("kind") == "actor"} | {
        SCENE,
        PLAYER,
        "@player",
    }
    try:
        outcomes = model_outcomes(turn)
        # The draft and the turn must agree on what actually reached the owner.
        if any(
            not (draft := turn.action_drafts.get(actor))
            or not draft.approved
            or draft.published_results != turn.action_outcomes[actor]
            for actor in outcomes
        ):
            return None
        rows = [
            row
            for actor, records in outcomes.items()
            if actor in turn.decisions
            for row in execution_frame.records(turn, records)
        ]
    except (CommandRejectedError, StaleControlError):
        return None
    operations = {
        transfer.operation_id: transfer for row in rows if (transfer := _transfer(row, actors))
    }
    scope = turn_controls.fingerprint([turn.control, frame.scene_id, sorted(actors), rows])
    effects = [
        {**row["effect"], "actor_id": row["actor_id"], "_publication_index": position}
        for position, row in enumerate(rows)
        if row["status"] == "applied" and row.get("effect") and not row.get("effect_omitted")
    ]
    return _Public(
        scope,
        actors,
        operations,
        effects,
        {row["operation_id"]: position for position, row in enumerate(rows)},
    )


def is_current(proof: Proof | None, turn: Any) -> bool:
    """Within a retry the review operation changes, but its published world effects must not."""
    if proof is None:
        return False
    public = _current_public(turn)
    return public is not None and public.scope == proof.publication_scope


def capture(turn: Any, review: Any, text: str, resolution: str) -> Proof | None:
    """Call only after the candidate has passed all existing narration review checks."""
    from backend.engine.chpm.rendering import _review_scope

    if not isinstance(review, passages.ReceiptReview) or not review.matches or review.rejections:
        return None
    public = _current_public(turn)
    available = index(text)
    if (
        public is None
        or not public.operations
        or review.review_scope != _review_scope(turn, available, resolution)
        or receipt_review.validate(review, turn, available)
    ):
        return None
    occurrences = spans(text)
    counts = Counter(passage.text for passage in occurrences.values())
    citations = []
    for claim in review.completed_changes or ():
        operation = public.operations.get(claim.operation_id)
        if operation is None:
            continue
        passage = occurrences[claim.passage_id]
        citations.append(
            Citation(
                claim.passage_id,
                passage.start,
                passage.end,
                _digest(passage.text),
                counts[passage.text] == 1,
                operation,
            )
        )
    bound = tuple(
        (key, value.start, value.end, _digest(value.text), counts[value.text] == 1)
        for key, value in occurrences.items()
    )
    return Proof(public.scope, review.review_scope, _digest(text), tuple(citations), bound)


def _directions(
    actions: Sequence[ItemAction], text: str, actors: set[str]
) -> dict[tuple[int, int, str], set[custody_effects.Reading]]:
    result: dict[tuple[int, int, str], set[custody_effects.Reading]] = defaultdict(set)
    for action in actions:
        src, dst, span = action.source_owner, action.destination_owner, action.evidence_span
        if (
            action.basis == "completed"
            and action.item_id
            and src != dst
            and src in actors
            and dst in actors
            and span
            and span.matches(text, action.evidence)
        ):
            result[span.start, span.end, action.item_id].add(custody_effects.read(action))
    return result


def _incompatible(actual: Transfer, source: str, destination: str) -> bool:
    if (source, destination) == (actual.source, actual.destination):
        return False
    # There is no performer field on ItemAction. An outgoing transfer by a different
    # donor can be an independent act. Compare the same custody endpoint, or a
    # direct inversion of the actor's pickup/drop between that actor and the room.
    return (
        SCENE in (actual.source, actual.destination)
        and (source, destination) == (actual.destination, actual.source)
    ) or (actual.tool in {"give_item", "put_down_item"} and source == actual.actor_id)


def _issue(
    citation: Citation, reading: custody_effects.Reading, reason: str = "custody_direction_mismatch"
) -> dict:
    actual = citation.transfer
    return {
        "reason_code": reason,
        "passage_id": citation.passage_id,
        "operation_id": actual.operation_id,
        "actor_id": actual.actor_id,
        "expected_public_result": {
            "tool": actual.tool,
            "target_id": actual.item,
            "source_owner": public_actor_id(actual.source),
            "destination_owner": public_actor_id(actual.destination),
        },
        "reported_public_direction": {
            "source_owner": public_actor_id(reading.source_owner),
            "destination_owner": public_actor_id(reading.destination_owner),
        },
    }


def _uncited(proof: Proof, public: _Public, readings: dict) -> list[Citation]:
    covered = {(entry.start, entry.end, entry.transfer.item) for entry in proof.citations}
    used = {entry.transfer.operation_id for entry in proof.citations}
    occurrences = {
        (start, end): (key, digest, unique) for key, start, end, digest, unique in proof.occurrences
    }
    result = []
    for (start, end, item), candidates in sorted(readings.items()):
        bound = occurrences.get((start, end))
        if bound is None or len(candidates) != 1 or (start, end, item) in covered:
            continue
        reading = next(iter(candidates))
        operations = [op for op in public.operations.values() if op.item == item]
        exact = [op for op in operations if (op.source, op.destination) == reading.direction]
        possible = [op for op in exact if op.operation_id not in used] or exact or operations[-1:]
        if not possible:
            continue
        key, digest, unique = bound
        operation = possible[0]
        used.add(operation.operation_id)
        result.append(Citation(key, start, end, digest, unique, operation))
    return result


def _reason(
    citation: Citation, reading: custody_effects.Reading, public: _Public, unassigned: set
) -> str:
    actual = citation.transfer
    if (actual.item, *reading.direction) not in unassigned and _incompatible(
        actual, *reading.direction
    ):
        return "custody_direction_mismatch"
    effect = {
        "item_id": actual.item,
        "source_owner": actual.source,
        "destination_owner": actual.destination,
        "disposition": "carried",
        "_publication_index": public.order[actual.operation_id],
    }
    if reading.direction == (
        actual.source,
        actual.destination,
    ) and not custody_effects.transfer_echo(reading, effect, public.effects):
        return "custody_placement_mismatch"
    return ""


def _completion_reason(
    proof: Proof,
    citation: Citation,
    reading: custody_effects.Reading,
    public: _Public,
    used: set,
    latest: dict,
) -> str:
    actual = citation.transfer
    if reading.direction != (actual.source, actual.destination):
        return ""
    cited_elsewhere = citation not in proof.citations and any(
        entry.transfer.operation_id == actual.operation_id for entry in proof.citations
    )
    if cited_elsewhere or actual.operation_id in used:
        return "custody_operation_reused"
    position = public.order[actual.operation_id]
    if position < latest.get(actual.item, -1):
        return "custody_operation_order_mismatch"
    used.add(actual.operation_id)
    latest[actual.item] = position
    return ""


def conflicts(
    proof: Proof | None, turn: Any, text: str, resolution: str, actions: Sequence[ItemAction]
) -> list[dict]:
    """Compare only one exact occurrence with one cited operation and one extracted direction."""
    from backend.engine.chpm.rendering import _review_scope

    if proof is None or not actions or proof.text_hash != _digest(text):
        return []
    public = _current_public(turn)
    if (
        public is None
        or proof.publication_scope != public.scope
        or proof.review_scope != _review_scope(turn, index(text), resolution)
    ):
        return []
    operations: dict[tuple[int, int, str], list[Citation]] = defaultdict(list)
    readings = _directions(actions, text, public.actors)
    citations = [*proof.citations, *_uncited(proof, public, readings)]
    for entry in citations:
        operations[entry.start, entry.end, entry.transfer.item].append(entry)
    # A reviewer may cite only the pickup in a compound transfer. A real
    # unassigned drop could belong here; a drop cited elsewhere has its own span.
    cited = {entry.transfer.operation_id for entry in citations}
    unassigned = {
        (op.item, op.source, op.destination)
        for op in public.operations.values()
        if op.operation_id not in cited
    }
    result = []
    used: set[str] = set()
    latest: dict[str, int] = {}
    for key, directions in sorted(readings.items()):
        entries = operations.get(key, [])
        if len(entries) != 1 or len(directions) != 1:
            continue
        citation, reading = entries[0], next(iter(directions))
        reason = _reason(citation, reading, public, unassigned) or _completion_reason(
            proof, citation, reading, public, used, latest
        )
        if reason:
            result.append(_issue(citation, reading, reason))
    return result[:_MAX_ISSUES]


def repeated_conflicts(
    first_proof: Proof | None,
    first_issues: Sequence[dict],
    turn: Any,
    text: str,
    actions: Sequence[ItemAction],
) -> list[dict]:
    """Carry a disputed reading across just one repair of the same public operations."""
    if first_proof is None or not first_issues or not actions:
        return []
    public = _current_public(turn)
    if public is None or first_proof.publication_scope != public.scope:
        return []
    citations = {
        (entry.transfer.operation_id, entry.passage_id): entry for entry in first_proof.citations
    }
    citations.update(_original_uncited(first_proof, public, first_issues))
    occurrences: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for key, passage in spans(text).items():
        occurrences[_digest(passage.text)].append((key, passage.start, passage.end))
    directions = _directions(actions, text, public.actors)
    result = []
    for issue in first_issues:
        operation_id, passage_id = issue.get("operation_id"), issue.get("passage_id")
        if not isinstance(operation_id, str) or not isinstance(passage_id, str):
            continue
        citation = citations.get((operation_id, passage_id))
        if citation is None:
            continue
        conflict = _repeated_issue(
            citation, issue, occurrences[citation.passage_hash], directions, public
        )
        if conflict is not None:
            result.append(conflict)
    return result[:_MAX_ISSUES]


def _repeated_reading(
    citation: Citation, issue: dict, readings: set, public: _Public
) -> custody_effects.Reading | None:
    reason = issue.get("reason_code", "custody_direction_mismatch")
    actual_directions = {(op.item, op.source, op.destination) for op in public.operations.values()}
    return next(
        (
            reading
            for reading in readings
            if _issue(citation, reading, reason) == issue
            and _reason(citation, reading, public, actual_directions) == reason
        ),
        None,
    )


def _repeated_issue(
    citation: Citation, issue: dict, occurrences: list, directions: dict, public: _Public
) -> dict | None:
    for key, start, end in occurrences:
        readings = directions.get((start, end, citation.transfer.item), set())
        reading = _repeated_reading(citation, issue, readings, public)
        if reading is not None:
            return _issue(
                replace(citation, passage_id=key, start=start, end=end),
                reading,
                issue.get("reason_code", "custody_direction_mismatch"),
            )
    return None


def _original_uncited(proof: Proof, public: _Public, issues: Sequence[dict]) -> dict:
    occurrences = {row[0]: row for row in proof.occurrences}
    result = {}
    for issue in issues:
        operation_id, passage_id = issue.get("operation_id"), issue.get("passage_id")
        if not isinstance(operation_id, str) or not isinstance(passage_id, str):
            continue
        operation = public.operations.get(operation_id)
        occurrence = occurrences.get(passage_id)
        if operation is not None and occurrence is not None:
            result[operation.operation_id, occurrence[0]] = Citation(*occurrence, operation)
    return result
