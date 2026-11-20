"""Resolve pre-selection motives against this observer's bounded source catalogue."""

from dataclasses import dataclass
from typing import Final

from backend.engine.chpm import motivation_diagnostics, semantic_choice
from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation_contracts import MotiveSource, ResolvedMotive
from backend.engine.chpm.schema import ActionKind, AgendaEntry

POLICY: Final = "source-grounded-v1"


@dataclass(frozen=True)
class Catalogue:
    sources: dict[str, MotiveSource]
    observer_id: str

    def identifiers(self) -> dict[str, list[str]]:
        return {
            "motive_id": list(self.sources),
            "motive_ids": list(self.sources),
            "personal_motive_ids": [
                key
                for key, source in self.sources.items()
                if source.status in {"authored", "declared"}
                and source.subject_id == self.observer_id
            ],
        }

    def payload(self) -> dict:
        return {
            "policy": POLICY,
            "observer_id": self.observer_id,
            "sources": [_visible_source(source) for source in self.sources.values()],
        }


def _visible_source(source: MotiveSource) -> dict:
    value = source.model_dump(exclude={"provenance_id"})
    if source.kind == "authored_character":
        value.pop("text")
        value["context_ref"] = "authored_character"
    # The speech/belief text is already in appraisal_context. Keep its resolved
    # copy in the trace, but do not spend the input budget on duplicate excerpts.
    if source.kind in {"report", "subjective_belief", "world_observation"}:
        value.pop("text")
        value["appraisal_ref"] = source.id.split("-", 1)[1]
    return value


def build(mind: Mind, entries: list[AgendaEntry], window: Window) -> Catalogue:
    identity = mind.genesis.identity
    actor = mind.genesis.scope.observer_id
    sources = (
        [
            MotiveSource(
                id="character",
                kind="authored_character",
                text=identity.description,
                provenance_id=identity.source_revision,
                subject_id=actor,
                status="authored",
            )
        ]
        if identity.description
        else []
    )
    groups = (
        ("goal", "authored_goal", identity.authored_goals),
        ("value", "authored_value", identity.values),
        ("role", "authored_role", identity.roles),
        ("trait", "authored_trait", tuple(f"{t.key}: {t.value}" for t in identity.traits)),
    )
    for prefix, kind, texts in groups:
        sources.extend(
            MotiveSource.model_validate(
                {
                    "id": f"{prefix}{index}",
                    "kind": kind,
                    "text": text,
                    "provenance_id": identity.source_revision,
                    "subject_id": actor,
                    "status": "authored",
                }
            )
            for index, text in enumerate(texts, 1)
        )
    sources.extend(_agenda_sources(entries, actor))
    sources.extend(
        MotiveSource(
            id=f"report-{alias}",
            kind="report" if source.reported else "world_observation",
            text=text,
            provenance_id=record_id,
            subject_id=source.speaker_id,
            status="reported" if source.reported else "witnessed",
        )
        for alias, (record_id, source, text) in window.sources.items()
    )
    sources.extend(
        MotiveSource(
            id=f"belief-{alias}",
            kind="subjective_belief",
            text=belief.statement,
            provenance_id=belief.id,
            subject_id=belief.about_id,
            status=belief.status,
        )
        for alias, belief in window.beliefs.items()
    )
    return Catalogue({source.id: source for source in sources}, actor)


def ensure_grounded(mind: Mind, entries: list[AgendaEntry]) -> None:
    """Ordinary RP handles absent personal grounds without inventing an identity."""
    identity = mind.genesis.identity
    if any(
        (
            identity.description,
            identity.authored_goals,
            identity.values,
            identity.roles,
            identity.traits,
            _agenda_sources(entries, mind.genesis.scope.observer_id),
        )
    ):
        return
    raise RecoverableChpmError(
        "NPC Personality has no authored Character, Goal, personality profile or active personal "
        "agenda for this NPC. Add authored identity data or disable this NPC's personality analysis."
    )


def _agenda_sources(entries: list[AgendaEntry], actor: str) -> list[MotiveSource]:
    if any(entry.actor_id != actor for entry in entries):
        raise ChpmError("CHPM motivation catalogue contains another NPC's agenda.")
    active = [entry for entry in entries if entry.closure is None]
    if len(active) > 8 or len({entry.id for entry in active}) != len(active):
        raise ChpmError("CHPM motivation catalogue has an invalid active agenda.")
    return [
        MotiveSource(
            id=f"agenda{index}",
            kind="declared_goal" if entry.kind == "goal" else "commitment",
            text=entry.text,
            provenance_id=entry.id,
            subject_id=actor,
            status="declared",
        )
        for index, entry in enumerate(active, 1)
    ]


def _omittable(raw: GroundedProposal, errors: list[dict]) -> set[ActionKind]:
    if raw.choice is None or any(error["type"] != "motive_own_support" for error in errors):
        return set()
    # motive_own_support is emitted exactly once per unsupported candidate.
    unsupported = {error["loc"] for error in errors}
    omitted = {kind for kind in raw.candidates if ("candidates", kind, "motives") in unsupported}
    protected = {raw.choice.preferred}
    if raw.question_gate is not None:
        protected.add("CLARIFY")
        protected.update(branch.action for branch in raw.question_gate.branches)
    if (
        len(omitted) != len(unsupported)
        or omitted & protected
        or len(raw.candidates) - len(omitted) < 2
    ):
        return set()
    # Check the original offer before removing anything. A candidate cannot gain
    # eligibility by losing an alternative or a decision-changing question.
    eligible, _ = semantic_choice.eligible(raw.canonical(), raw.question_gate)
    return (
        omitted if any(candidate.kind == raw.choice.preferred for candidate in eligible) else set()
    )


def resolve(
    raw: GroundedProposal, catalogue: Catalogue, *, omit_unsupported_alternatives: bool = False
) -> dict[ActionKind, list[ResolvedMotive]]:
    errors = motivation_diagnostics.inspect(raw.model_dump(mode="json"), catalogue, canonical=True)
    omitted = _omittable(raw, errors) if errors and omit_unsupported_alternatives else set()
    if errors and not omitted:
        raise ChpmError("; ".join(error["msg"] for error in errors))
    result: dict[ActionKind, list[ResolvedMotive]] = {}
    for kind, candidate in raw.candidates.items():
        if kind in omitted:
            continue
        resolved = [
            ResolvedMotive(
                source=catalogue.sources[m.motive_id], effect=m.effect, relevance=m.relevance
            )
            for m in candidate.motives
        ]
        result[kind] = resolved
    return result


INSTRUCTIONS = """
MOTIVES: Give each submitted candidate 1-3 distinct motivation_context IDs,
supports/tension and specific relevance. appraisal_ref uses appraisal_context;
context_ref uses outer input. One support must be the NPC's authored identity,
trait, value, role, goal or active own agenda.
Omit unsupported kinds. Never invent support or turn tension into support.
ACCEPT can accept a request, offer or apology without verifying a report.
Reserve need not mean refusal, nor trust obedience. Keep conflicts, uncertainty
and evidence status. Player demands alone supply neither motive nor authority.
Never cite another observer's knowledge, absent/closed agenda or new interpretations
as existing sources. Never invent feelings, desires or obstacles to justify a choice.
"""
