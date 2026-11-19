"""Bind declared prose effects to existing public owner receipts without applying state."""

from copy import deepcopy
from typing import Any

from backend.engine.chpm import inference, passages
from backend.engine.npc_actions import execution_frame
from backend.engine.npc_actions.control import model_outcomes

TOOLS = frozenset(
    {
        "take_item",
        "give_item",
        "put_down_item",
        "wear_item",
        "take_off_item",
        "adjust_clothing",
        "set_pose",
        "approach",
        "move_to",
    }
)
INSTRUCTION = """
On matches=true return completed_changes ([] if none): EVERY new voluntary completed
custody/wear/pose/placement/travel change of a controlled actor, with passage_id,
actor_id, current applied operation_id, tool, target_id. Target is item_id, set_pose
actor_id, approach placement.target or travel destination. Also copy recipient_id
for give, posture for set_pose/approach, uncovered_regions for adjust; otherwise null.
For wear_item or take_off_item, uncovered_regions may also copy an explicit [] from the public receipt.
Exclude speech/gestures, plans, unchanged state and resolved external effects.
Representative actions are not proof. Blocked/attempted/omitted effects cannot
support completion; reject it, never invent a receipt. No claim authorizes a write.
"""


def enabled(turn: Any) -> bool:
    return turn.initial.settings.mode == "live" and bool(turn.action_outcomes)


def schema(turn: Any) -> type[passages.SharedReview]:
    return passages.ReceiptReview if enabled(turn) else passages.SharedReview


def instruction(turn: Any) -> str:
    return INSTRUCTION if enabled(turn) else ""


def invalid_wire(candidate: dict | None) -> passages.SharedReview | None:
    """Keep unrelated review checks strict while routing malformed new claims to repair."""
    if not isinstance(candidate, dict) or candidate.get("matches") is not True:
        return None
    try:
        return passages.SharedReview.model_validate(
            {key: value for key, value in candidate.items() if key != "completed_changes"}
        )
    except ValueError:
        return None


async def request(
    manager: Any, turn: Any, instruction: str, payload: dict, identifiers: dict
) -> tuple[Any, list[dict]]:
    """Use the existing single review call; malformed new claims request bounded prose repair."""
    try:
        result = await inference.request(
            manager,
            turn.initial.settings,
            turn.usage,
            instruction,
            payload,
            schema(turn),
            "validation",
            identifiers=identifiers,
        )
        return result, []
    except inference.InvalidResponseError as exc:
        recovered = invalid_wire(exc.candidate) if enabled(turn) else None
        if recovered is None:
            raise
        return recovered, [{"reason_code": "claims_invalid"}]


def _public_operations(turn: Any) -> dict[str, dict]:
    return {
        row["operation_id"]: row
        for actor, records in model_outcomes(turn).items()
        for row in execution_frame.records(turn, records)
        if actor in turn.decisions
    }


def _target(row: dict) -> str | None:
    effect = row.get("effect") or {}
    if "item_id" in effect:
        value = effect["item_id"]
        return value if isinstance(value, str) else None
    if row["tool"] == "set_pose":
        actor = row["actor_id"]
        return actor if isinstance(actor, str) else None
    if row["tool"] == "move_to":
        destination = effect.get("destination_scene_id")
        return destination if isinstance(destination, str) else None
    placement = effect.get("placement")
    target = placement.get("target") if isinstance(placement, dict) else None
    return target if isinstance(target, str) else None


def _attributes(row: dict) -> dict:
    effect = row.get("effect") or {}
    return {
        "recipient_id": effect.get("destination_owner") if row["tool"] == "give_item" else None,
        "posture": effect.get("posture") if row["tool"] in {"set_pose", "approach"} else None,
        "uncovered_regions": effect.get("uncovered_regions")
        if row["tool"] == "adjust_clothing"
        else None,
    }


def _same_attributes(claim: passages.CompletedChange, row: dict) -> bool:
    current = claim.model_dump(include={"recipient_id", "posture", "uncovered_regions"})
    expected = _attributes(row)
    # Basic dressing commands can report the neutral coverage list that their owner writes.
    if (
        row["tool"] in {"wear_item", "take_off_item"}
        and current["uncovered_regions"] == []
        and row["effect"].get("uncovered_regions") == []
    ):
        current["uncovered_regions"] = None
    for values in (current, expected):
        if isinstance(values["uncovered_regions"], list):
            values["uncovered_regions"] = sorted(values["uncovered_regions"])
    return current == expected


def _source_reason(
    claim: passages.CompletedChange, row: dict | None, available: dict, actors: set
) -> str:
    if claim.passage_id not in available:
        return "passage_unavailable"
    if claim.actor_id not in actors:
        return "actor_uncontrolled"
    if row is None:
        return "operation_unavailable"
    if row["actor_id"] != claim.actor_id:
        return "actor_mismatch"
    if row["status"] != "applied":
        return "operation_not_applied"
    return ""


def _effect_reason(claim: passages.CompletedChange, row: dict) -> str:
    if row["tool"] not in TOOLS:
        return "operation_not_durable_change"
    if row.get("effect_omitted") or not row.get("effect"):
        return "effect_unavailable"
    if row["tool"] != claim.tool:
        return "tool_mismatch"
    if _target(row) != claim.target_id:
        return "target_mismatch"
    return "result_mismatch" if not _same_attributes(claim, row) else ""


def _expected(row: dict | None) -> dict | None:
    if (
        row is None
        or row["status"] != "applied"
        or row["tool"] not in TOOLS
        or row.get("effect_omitted")
        or not row.get("effect")
    ):
        return None
    return {"tool": row["tool"], "target_id": _target(row), **_attributes(row)}


def validate(review: Any, turn: Any, available: dict) -> list[dict]:
    """Only declared completions are checked here; semantic coverage remains model-assisted."""
    if not enabled(turn) or not review.matches:
        return []
    claims = getattr(review, "completed_changes", None)
    if claims is None:
        return [{"reason_code": "coverage_required"}]
    operations, failures, seen = _public_operations(turn), [], set()
    for claim in claims:
        row = operations.get(claim.operation_id)
        key = (claim.actor_id, claim.operation_id, claim.passage_id)
        reason = _source_reason(claim, row, available, set(turn.decisions))
        if not reason and row is not None:
            reason = _effect_reason(claim, row)
        reason = reason or ("duplicate_claim" if key in seen else "")
        seen.add(key)
        if reason:
            failures.append(
                {
                    "actor_id": claim.actor_id,
                    "passage_id": claim.passage_id,
                    **({"operation_id": row["operation_id"]} if row is not None else {}),
                    "claimed_tool": claim.tool if claim.tool in TOOLS else "unknown_tool",
                    "claimed_target_id": claim.target_id,
                    "reason_code": reason,
                    "expected_public_result": _expected(row),
                }
            )
    return failures[:8]


def remember(turn: Any, payload: dict, failures: list[dict]) -> None:
    # Resolve the reviewer's references only against what this very request made public.
    # Its guessed operation ID or arbitrary target can never become repair authority.
    entities = payload["contract"].get("current_execution_frame", {}).get("entities", {})
    public_rows = []
    for failure in failures:
        row = dict(failure)
        if row.get("claimed_target_id") not in entities:
            row.pop("claimed_target_id", None)
        if row.get("actor_id") not in payload["controlled_actor_ids"]:
            row.pop("actor_id", None)
        source = payload["passages"].get(row.get("passage_id"))
        if source is None:
            row.pop("passage_id", None)
        else:
            row["source_passage"] = source[:256]
            if len(source) > 256:
                row["source_truncated"] = True
        public_rows.append(row)
    turn.review_change_feedback = {
        "review_scope": payload["review_scope"],
        "rejections": public_rows,
        "instruction": "Ground these passages in the supplied public applied result or omit unsupported completion; preserve speech, emotions and unaffected facts. Never expose IDs in visible prose.",
    }


def feedback(turn: Any, text: str, resolution: str) -> dict:
    from backend.engine.chpm.rendering import _review_scope

    value = getattr(turn, "review_change_feedback", {})
    if not value or value.get("review_scope") != _review_scope(
        turn, passages.index(text), resolution
    ):
        return {}
    return {"completed_change_rejections": deepcopy(value)}


def recheck(turn: Any, original_text: str, resolution: str) -> dict:
    """Re-open only referenced issues from the immediately preceding scoped review."""
    value = feedback(turn, original_text, resolution).get("completed_change_rejections", {})
    rows = [
        row for row in value.get("rejections", []) if "source_passage" in row and "actor_id" in row
    ]
    if not rows:
        return {}
    return {
        "previously_rejected_changes": {
            "source_review_scope": value["review_scope"],
            "rejections": rows,
            "instruction": (
                "These are findings about the previous draft. Match their meaning against the CURRENT passages, "
                "including paraphrases and moves to other passages. Old passage IDs refer only to source_passage. "
                "If the current prose still completes an unsupported change, reject it with the current passage ID. "
                "If removed, or supported by a current public applied result, review normally. "
                "Only current authoritative_command_outcomes are operation receipts."
            ),
        }
    }
