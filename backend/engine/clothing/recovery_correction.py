"""Explicit corrections repair a preview, never bypass evidence or apply possessions."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from backend.engine.clothing.body_schema import BodySlot
from backend.engine.clothing.context import detail_settings
from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.recovery_evaluation import evaluated_preview
from backend.engine.clothing.recovery_payload import build_payload
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryProposal
from backend.engine.clothing.schema import Region


class RecoveryCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["worn", "carried"]
    evidence: str = Field(min_length=4, max_length=800)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=100)
    uncovered_regions: list[Region] = Field(default_factory=list, max_length=7)
    placement_evidence: str = Field(default="", max_length=800)
    restore_coverage: StrictBool = False
    attachment_slot: BodySlot | None = None

    @model_validator(mode="after")
    def coherent(self) -> "RecoveryCorrection":
        if self.attachment_slot:
            if (
                self.status != "worn"
                or self.uncovered_regions
                or self.placement_evidence
                or self.restore_coverage
            ):
                raise ValueError(
                    "Body placement requires placed state without clothing coverage fields."
                )
            return self
        if self.status == "carried" and (
            self.uncovered_regions or self.placement_evidence or self.restore_coverage
        ):
            raise ValueError("Removed garments cannot have partial placement.")
        if self.restore_coverage and (self.uncovered_regions or not self.placement_evidence):
            raise ValueError("Restoring coverage requires an exact quote and no exposed regions.")
        if not self.restore_coverage and bool(self.uncovered_regions) != bool(
            self.placement_evidence
        ):
            raise ValueError("Partial placement requires both regions and an exact quote.")
        if len(set(self.uncovered_regions)) != len(self.uncovered_regions):
            raise ValueError("Exposed regions must be unique.")
        return self


def _corrected_proposal(
    preview: dict, index: int, correction: RecoveryCorrection
) -> RecoveryProposal:
    reviewable = {row["index"] for row in preview.get("rejected_entries") or []} | {
        row["proposal_index"] for row in preview.get("accepted") or []
    }
    if index not in reviewable:
        raise ValueError("Choose an available entry from this preview.")
    proposal = RecoveryProposal.model_validate(deepcopy(preview.get("proposal")))
    if not 0 <= index < len(proposal.entries):
        raise ValueError("Unknown entry; generate a new preview.")
    entry = proposal.entries[index]
    changed = {
        **entry.model_dump(),
        "source_message_id": correction.source_message_id or entry.source_message_id,
        "action": {
            **entry.action.model_dump(),
            "basis": "observed_wear" if correction.status == "worn" else "completed",
            "disposition": correction.status,
            "evidence": correction.evidence,
            "attachment_slot": correction.attachment_slot or entry.action.attachment_slot,
        },
        "uncovered_regions": correction.uncovered_regions,
        "placement_evidence": correction.placement_evidence,
        "restore_coverage": correction.restore_coverage,
    }
    proposal.entries[index] = RecoveryEntry.model_validate(changed)
    return proposal


def _request(args: str, preview: dict) -> tuple[int, RecoveryProposal]:
    parts = args.split(maxsplit=3)
    if len(parts) != 4 or parts[1] != preview.get("token"):
        raise ValueError("Preview is missing or has been replaced. Generate a new preview.")
    if len(parts[2]) > 2 or not parts[2].isascii() or not parts[2].isdecimal():
        raise ValueError("Choose an available entry from this preview.")
    if len(parts[3]) > 12000:
        raise ValueError("Correction is too large. Copy short exact quotes.")
    index = int(parts[2])
    correction = RecoveryCorrection.model_validate_json(parts[3])
    return index, _corrected_proposal(preview, index, correction)


async def debug_wardrobe_correct(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Wardrobe correction requires debug mode and a session avatar."
    preview = (state.entity_states or {}).get(KEY) or {}
    try:
        index, proposal = _request(args, preview)
        context = await recovery_context(db, state, avatar, preview["npc_id"])
        if context["fingerprint"] != preview.get("fingerprint"):
            return "DEBUG ERROR: Story or state changed after preview. Generate a new preview."
        detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
        context, _ = build_payload(context, detailed)
        reviewed = evaluated_preview(context, proposal, detailed, state.session_id)
        if index not in {row["proposal_index"] for row in reviewed["accepted"]}:
            reasons = [*reviewed["errors"], *reviewed["skipped"]]
            raise ValueError(
                "Correction failed validation; preview unchanged. " + " ".join(reasons)
            )
        others = [row for row in preview.get("accepted", []) if row.get("proposal_index") != index]
        if any(row not in reviewed["accepted"] for row in others):
            raise ValueError(
                "Correction conflicts with another validated garment; preview unchanged."
            )
    except ValidationError:
        return "DEBUG ERROR: Invalid correction. Choose worn or carried and provide exact quotes; only worn garments can change placement."
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"
    state.entity_states = {
        **state.entity_states,
        KEY: {**preview, **reviewed, "token": str(uuid4())},
    }
    return "DEBUG: Recovery proposal corrected. Review and select the garment before applying. No clothing was changed."
