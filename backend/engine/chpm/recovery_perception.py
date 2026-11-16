"""Classify a few source-bound past fragments within the existing perception call."""

from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.host_state import Source
from backend.engine.chpm.perception_fragments import Projection
from backend.engine.chpm.recovery_contracts import HistoricalObservation
from backend.engine.chpm.recovery_queue import Batch
from backend.engine.chpm.schema import Contract

INSTRUCTION = """
Also classify EVERY unreviewed_history fragment in history_fragments, keyed by its
supplied h-ID. These are older saved events, not the current player input.
Use kind=speech only for clearly attributed spoken words, with a speaker_id KEY
from present_speakers_at_source; use public_event for perceptible narration.
For each fragment choose observers only from its eligible_observers_by_fragment
list. A prior turn's eligibility is not proof that this NPC heard every passage.
Use private, unobserved or uncertain with observers=[] and speaker_id=null when
appropriate; a mixed private/public fragment is uncertain. Do not expose private
thoughts or infer observers from later knowledge. For public_event use speaker_id=null.
Classify only the supplied fragments; adjacent story context can resolve attribution
but cannot supply omitted events. No past decisions, emotional updates, new world
outcomes or present ongoing actions may be reconstructed by this classification.
The host retains exact text, scene, game minute and unresolved fragments separately.
Return current fragments and history_fragments as separate objects in the schema.
"""


class Fragment(Contract):
    kind: Literal["speech", "public_event", "private", "unobserved", "uncertain"]
    observers: list[str] = Field(default_factory=list, max_length=20)
    speaker_id: str | None = None


class RecoveryProjection(Projection):
    # Validate this independent section after current perception has succeeded.
    history_fragments: Annotated[
        Any, BeforeValidator(lambda value: value, json_schema_input_type=dict[str, Fragment])
    ] = None


def bind(batch: Batch, result: Any) -> None:
    batch.accepted, batch.checked, batch.uncertain = {}, set(), {}
    raw = getattr(result, "history_fragments", None)
    if not isinstance(raw, dict) or set(raw) != set(batch.available):
        batch.error = "Historical fragments were not all classified."
        return
    proposed: dict[str, list[Source]] = {actor: [] for actor in batch.offsets}
    try:
        for key, fragment in raw.items():
            _fragment(batch, key, Fragment.model_validate(fragment), proposed)
    except ValueError as exc:
        batch.error = str(exc)
        return
    batch.accepted, batch.checked = proposed, set(batch.offsets)


def _fragment(batch: Batch, key: str, fragment: Fragment, proposed: dict) -> None:
    observers = set(fragment.observers)
    eligible = {actor for actor, cursor in batch.offsets.items() if int(key[1:]) >= cursor}
    if not observers <= eligible or len(observers) != len(fragment.observers):
        raise ValueError("Historical perception named an unproven observer.")
    if fragment.kind in {"private", "unobserved", "uncertain"}:
        if observers:
            raise ValueError("Private or uncertain history cannot be admitted to NPC memory.")
        if fragment.kind == "uncertain":
            passage = batch.available[key]
            for actor in eligible:
                batch.uncertain.setdefault(actor, []).append(
                    EvidenceSpan(start=passage.start, end=passage.end)
                )
        return
    if fragment.kind == "speech" and fragment.speaker_id not in batch.audit.speakers:
        raise ValueError("Historical speech needs an established speaker.")
    passage = batch.available[key]
    for actor in observers:
        proposed[actor].append(
            Source(
                message_id=batch.message.id,
                revision_id=batch.message.revision_id,
                content_hash=batch.audit.content_hash,
                role="assistant",
                speaker_id=str(fragment.speaker_id) if fragment.kind == "speech" else actor,
                kind="speech" if fragment.kind == "speech" else "narration",
                text=passage.text,
                history=HistoricalObservation(
                    scene_id=batch.audit.scene_id,
                    game_minute=batch.audit.game_minute,
                    evidence_span=EvidenceSpan(start=passage.start, end=passage.end),
                ),
            )
        )
