"""Use one existing narration repair for source-bound physical outcome disagreements."""

from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.state_rejection_trace import reject
from backend.engine.chpm import passages, receipt_review, rendering
from backend.engine.chpm.errors import ChpmError, StaleControlError
from backend.engine.chpm.runtime import Turn, current
from backend.engine.npc_actions.custody_check import CustodyDisagreementError, Recheck
from backend.engine.turn_replay import drafts


async def reconcile(
    manager: Any,
    text: str,
    *,
    resolve: Callable[..., Awaitable[list[str]]],
    resolution: str,
    system_prompt: str,
) -> tuple[str, list[str]]:
    try:
        return text, await resolve(text, resolution=resolution)
    except CustodyDisagreementError as exc:
        check = exc.recheck
    # The candidate was buffered. Recovery must never offer it as an interrupted visible draft.
    drafts.observe(manager, "")
    turn = current(manager)
    if turn is None or turn.simplified or turn.reviewed_custody is not check.proof:
        raise StaleControlError("The disputed custody citation belongs to an inactive review.")
    reject(
        "npc_actions",
        "custody_citation_mismatch",
        "Current narration and physical owner results disagree.",
        review_operation_id=turn.review_operation["operation_id"],
        discrepancies=check.failures,
    )
    if turn.usage.repairs or turn.usage.calls + 2 > turn.initial.settings.max_calls_per_turn:
        raise ChpmError("NPC custody disagrees with narration and its repair budget is exhausted.")
    revised = await _correct(manager, turn, text, resolution, system_prompt, check)
    messages = await resolve(revised, resolution=resolution, custody_retry=check)
    if current(manager) is not turn or not check.checked:
        raise ChpmError("The corrected narration did not receive a confirmed item check.")
    drafts.observe(manager, revised)
    return revised, messages


async def _correct(
    manager: Any, turn: Turn, text: str, resolution: str, system: str, check: Recheck
) -> str:
    payload = rendering._review_payload(turn, passages.index(text), resolution)
    receipt_review.remember(turn, payload, check.failures)
    turn.verdict = None
    issues = [
        "Correct the disputed physical passage. Describe only current owner facts and published results; preserve expressive details."
    ]
    revised = await rendering._repair(manager, turn, text, resolution, issues, system)
    classification_only = all(
        issue.get("reason_code") in {"pose_classification_required", "pose_classification_invalid"}
        for issue in check.failures
    )
    if not revised.strip() or (
        not classification_only
        and rendering._candidate_key(revised) == rendering._candidate_key(text)
    ):
        raise ChpmError("The narrator repeated the rejected custody description.")
    verdict = await rendering._review(manager, turn, revised, resolution, repaired_from=text)
    if not verdict.matches:
        raise ChpmError("The corrected custody description failed its narration review.")
    turn.verdict = verdict
    return revised
