"""Audit classified final-frame poses without granting prose any state-writing authority."""

from typing import Any

from backend.engine import turn_controls
from backend.engine.npc_actions import custody_citations, execution_frame, pose_audit_owner
from backend.engine.npc_actions.pose_audit_sources import Pending, PoseAuditUnavailableError, repeat
from backend.engine.npc_actions.pose_audit_sources import digest as _digest
from backend.engine.npc_actions.pose_audit_sources import read as _read
from backend.engine.scene_continuity.schema import Action, FramePose
from backend.engine.scene_staging.schema import SceneDelta
from backend.engine.visual_novel.config import read_settings

INSTRUCTIONS = """
FINAL FRAME POSE AUDIT: When npc_pose_audit is supplied, classify every final_frame_actions
passage involving its controlled_actor_ids with poses. [] certifies an expressive gesture,
speech or ordinary detail with no lasting pose/placement. Null/omission is unclassified.
Otherwise list each asserted actor_id, basis=current or completed, posture and/or placement.
Use public target IDs from npc_pose_audit.targets, never an invented prop or a prose label.
Current describes an existing owner's state; completed asserts a newly performed change.
Do not erase an unsupported change from this audit merely because a command failed.
These are source-bound observations, never commands or permission to change staging.
A pose alone supplies no chair or support. Preserve negations, uncertainty and history.
For a quotation, history, negation or hypothesis use timeframe=noncurrent and poses=[].
Those rows audit source meaning only and never enter the current illustration frame.
"""


def _control(manager: Any) -> dict | None:
    from backend.engine.npc_actions.reconciliation import context as command_context

    turn = getattr(manager, "_chpm_turn", None)
    if turn is None or getattr(turn.initial.settings, "npc_decision_mode", None) != "two_phase":
        return None
    return command_context(manager)


def prepare(manager: Any, narration: str, actors: dict, rows: list[Any]) -> dict | None:
    prior = getattr(manager, "_npc_pose_audit", None)
    manager._npc_prior_pose_audit = (
        prior
        if isinstance(prior, Pending) and turn_controls.bind_current(manager, prior.control)
        else None
    )
    manager._npc_pose_audit = None
    manager._npc_pose_audit_rows = list(rows)
    control = _control(manager)
    if not control:
        return None
    current = pose_audit_owner.facts(manager, actors, rows)
    manager._npc_pose_audit = Pending(
        dict(manager._chpm_turn.control),
        _digest(narration),
        turn_controls.fingerprint(current),
        getattr(getattr(manager._chpm_turn, "reviewed_custody", None), "review_scope", None),
    )
    return {
        "npc_pose_audit": {
            "controlled_actor_ids": control["controlled_actor_ids"],
            "current_owner_poses": current,
            "targets": pose_audit_owner.targets(manager._chpm_turn),
            "staging_enabled": read_settings(manager.state).scene_staging,
        }
    }


def instructions(manager: Any) -> str:
    return INSTRUCTIONS if isinstance(getattr(manager, "_npc_pose_audit", None), Pending) else ""


def _passage(proof: custody_citations.Proof, action: Action | SceneDelta) -> str | None:
    span = action.evidence_span
    if span is None:
        return None
    return next((row[0] for row in proof.occurrences if row[1] <= span.start < row[2]), None)


def _failure(
    proof: custody_citations.Proof,
    actor: str,
    action: Action | SceneDelta | None,
    reason: str,
    current: dict,
) -> dict:
    result = {
        "actor_id": actor,
        "reason_code": reason,
        "expected_public_result": {"current_owner_pose": current},
    }
    if action is not None and (passage := _passage(proof, action)) is not None:
        result.update(passage_id=passage, source_passage_hash=_digest(action.evidence))
    return result


def _target_reason(pose: FramePose, targets: dict) -> str:
    if pose.placement is None:
        return ""
    kind = "actor" if pose.placement.target_kind == "character" else "item"
    return "" if targets.get(pose.placement.target) == kind else "pose_target_unavailable"


def _matching_receipt(pose: FramePose, records: list[dict]) -> bool:
    return any(_receipt_matches(pose, row) for row in records)


def _receipt_matches(pose: FramePose, row: dict) -> bool:
    effect = row.get("effect") or {}
    if (
        row["status"] != "applied"
        or row["tool"] not in {"set_pose", "approach"}
        or row.get("effect_omitted")
    ):
        return False
    if pose.clear:
        return effect.get("posture") == "unknown" and not effect.get("placement")
    return (pose.posture is None or effect.get("posture") == pose.posture) and (
        pose.placement is None or effect.get("placement") == pose.placement.model_dump()
    )


def _pose_reason(
    pose: FramePose,
    current: dict,
    targets: dict,
    records: list[dict],
    external: set[str] | frozenset[str] = frozenset(),
) -> str:
    reason = _target_reason(pose, targets)
    if reason:
        return reason
    if (
        pose.clear
        and current
        or pose.posture is not None
        and current.get("posture") != pose.posture
        or pose.placement is not None
        and current.get("placement") != pose.placement.model_dump()
    ):
        return "pose_state_mismatch"
    fields = ({"posture"} if pose.posture is not None else set()) | (
        {"placement"} if pose.placement is not None else set()
    )
    if pose.clear:
        fields = {"posture", "placement"}
    if pose.basis == "completed" and not (fields <= external or _matching_receipt(pose, records)):
        return "pose_operation_unavailable"
    return ""


def _row_failures(
    raw: Any,
    manager: Any,
    proof: custody_citations.Proof,
    narration: str,
    current: dict,
    control: dict,
    external: dict,
) -> list[dict]:
    body, action = _read(raw)
    ids = body.get("actor_ids")
    actors = (
        set(ids) & set(control["controlled_actor_ids"])
        if isinstance(ids, list) and all(isinstance(v, str) for v in ids)
        else set()
    )
    if not actors:
        return []
    reason = "pose_classification_invalid" if action is None else ""
    if action is not None and (
        action.evidence_span is None
        or not action.evidence_span.matches(narration, action.evidence)
        or _passage(proof, action) is None
    ):
        reason = "pose_source_unavailable"
    if reason or action is not None and action.poses is None:
        return [
            _failure(
                proof,
                actor,
                action,
                reason or "pose_classification_required",
                current.get(actor, {}),
            )
            for actor in sorted(actors)
        ]
    if action is None:
        raise PoseAuditUnavailableError("Final-frame action classification is unavailable.")
    if action.timeframe != "current":
        return []
    turn = manager._chpm_turn
    targets = pose_audit_owner.targets(turn)
    result = []
    for pose in action.poses or []:
        if pose.actor_id not in actors:
            continue
        records = execution_frame.records(turn, control["outcomes"].get(pose.actor_id, []))
        reason = _pose_reason(
            pose,
            current.get(pose.actor_id, {}),
            targets,
            records,
            external.get(pose.actor_id, set()),
        )
        if reason:
            result.append(
                _failure(proof, pose.actor_id, action, reason, current.get(pose.actor_id, {}))
            )
    return result


def _covers(action: Action, change: SceneDelta) -> bool:
    parent, child = action.evidence_span, change.evidence_span
    return (
        change.entity_id in action.actor_ids
        and parent is not None
        and child is not None
        and parent.start <= child.start < child.end <= parent.end
    )


def _nominal_failures(
    manager: Any,
    preview: pose_audit_owner.Preview,
    actions: list[Action],
    proof: custody_citations.Proof,
    narration: str,
) -> list[dict]:
    from backend.engine.scene_staging.attribution import _new_fields

    failures = []
    pending = manager._npc_pose_audit
    for change in preview.rejected:
        current = preview.facts.get(change.entity_id, {})
        related = [action for action in actions if _covers(action, change)]
        if related and any(action.timeframe == "noncurrent" for action in related):
            continue
        fields = _new_fields(change, current)
        if fields == {"placement"} and any(
            pose.actor_id == change.entity_id
            and pose.placement is not None
            and pose.placement.model_dump() == current.get("placement")
            for action in related
            for pose in action.poses or []
        ):
            continue
        if change.evidence_span is not None and change.evidence_span.matches(
            narration, change.evidence
        ):
            pending.sources[change.entity_id, _digest(change.evidence)] = change.evidence
        failures.append(_failure(proof, change.entity_id, change, "pose_state_mismatch", current))
    return failures


def check(
    manager: Any, response: Any, extraction: Any, actors: dict, narration: str, retry: Any = None
) -> list[dict]:
    control = _control(manager)
    if not control:
        return []
    turn = manager._chpm_turn
    proof = turn.reviewed_custody
    pending = getattr(manager, "_npc_pose_audit", None)
    if (
        not isinstance(pending, Pending)
        or pending.source_hash != _digest(narration)
        or not turn_controls.bind_current(manager, pending.control)
    ):
        raise PoseAuditUnavailableError("The final-frame pose audit belongs to an inactive source.")
    if proof is None or not custody_citations.is_current(proof, turn):
        raise PoseAuditUnavailableError(
            "Current public command outcomes are unavailable for pose review."
        )
    rows = getattr(getattr(manager, "_shared_scene_staging", None), "rows", None)
    # The item owner already supplied these exact session rows before model dispatch.
    rows = rows if rows is not None else getattr(manager, "_npc_pose_audit_rows", [])
    before = pose_audit_owner.facts(manager, actors, rows)
    if turn_controls.fingerprint(before) != pending.state_hash:
        raise PoseAuditUnavailableError(
            "The current pose owner changed during final-frame extraction."
        )
    staged = response.staging if hasattr(response, "staging") else None
    preview = pose_audit_owner.preview(manager, narration, staged, actors, rows)
    current = preview.facts
    actions = [
        action for raw in extraction.final_frame_actions if (action := _read(raw)[1]) is not None
    ]
    for action in actions:
        if action.evidence_span is not None and action.evidence_span.matches(
            narration, action.evidence
        ):
            pending.sources.update(
                {
                    (actor, _digest(action.evidence)): action.evidence
                    for actor in action.actor_ids
                    if actor in control["controlled_actor_ids"]
                }
            )
    failures = [
        issue
        for raw in extraction.final_frame_actions
        for issue in _row_failures(
            raw, manager, proof, narration, current, control, preview.external
        )
    ]
    failures.extend(_nominal_failures(manager, preview, actions, proof, narration))
    failures.extend(
        repeat(
            getattr(manager, "_npc_prior_pose_audit", None),
            retry,
            narration,
            extraction.final_frame_actions,
            current,
        )
    )
    if not failures:
        pending.approved.extend(actions)
    return failures[:8]


async def enforce(manager: Any, narration: str) -> None:
    pending = getattr(manager, "_npc_pose_audit", None)
    if not isinstance(pending, Pending) or not pending.approved:
        return
    control = _control(manager)
    if (
        not control
        or pending.source_hash != _digest(narration)
        or not turn_controls.bind_current(manager, pending.control)
    ):
        raise PoseAuditUnavailableError("The final-frame pose audit lost its current source.")
    from backend.engine.clothing.context import actor_records
    from backend.engine.clothing.visuals import session_objects

    rows = await session_objects(manager.db, manager.game_id, refresh=True)
    actors = actor_records(manager, rows)
    current = pose_audit_owner.facts(manager, actors, rows)
    external = pose_audit_owner.external_fields(manager, narration)
    proof = manager._chpm_turn.reviewed_custody
    if proof is None or not custody_citations.is_current(proof, manager._chpm_turn):
        raise PoseAuditUnavailableError(
            "The physical frame lost its current public outcome binding."
        )
    issues = [
        issue
        for action in pending.approved
        for issue in _row_failures(action, manager, proof, narration, current, control, external)
    ]
    if issues:
        from backend.engine.turn_replay import drafts

        drafts.observe(manager, "")
        raise PoseAuditUnavailableError(
            "Accepted physical prose does not match the final staging owner."
        )
