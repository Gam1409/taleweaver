"""Resolve pre-selection motives against this observer's bounded source catalogue."""

from dataclasses import dataclass
from typing import Final

from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation_contracts import MotiveSource, ResolvedMotive
from backend.engine.chpm.schema import ActionKind, AgendaEntry

POLICY: Final = "source-grounded-v1"


@dataclass(frozen=True)
class Catalogue:
    sources: dict[str, MotiveSource]
    observer_id: str

    def payload(self) -> dict:
        return {
            "policy": POLICY,
            "observer_id": self.observer_id,
            "sources": [_visible_source(source) for source in self.sources.values()],
        }


def _visible_source(source: MotiveSource) -> dict:
    value = source.model_dump(exclude={"provenance_id"})
    # The speech/belief text is already in appraisal_context. Keep its resolved
    # copy in the trace, but do not spend the input budget on duplicate excerpts.
    if source.kind in {"report", "subjective_belief", "world_observation"}:
        value.pop("text")
        value["appraisal_ref"] = source.id.split("-", 1)[1]
    return value


def build(mind: Mind, entries: list[AgendaEntry], window: Window) -> Catalogue:
    identity = mind.genesis.identity
    actor = mind.genesis.scope.observer_id
    sources = [
        MotiveSource(
            id="character",
            kind="authored_character",
            text=identity.description,
            provenance_id=identity.source_revision,
            subject_id=actor,
            status="authored",
        )
    ]
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
            kind="report" if source.kind == "speech" else "world_observation",
            text=text,
            provenance_id=record_id,
            subject_id=source.speaker_id,
            status="reported" if source.kind == "speech" else "witnessed",
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


def resolve(raw: GroundedProposal, catalogue: Catalogue) -> dict[ActionKind, list[ResolvedMotive]]:
    result: dict[ActionKind, list[ResolvedMotive]] = {}
    for kind, candidate in raw.candidates.items():
        ids = [motive.motive_id for motive in candidate.motives]
        if len(ids) != len(set(ids)) or not set(ids) <= catalogue.sources.keys():
            raise ChpmError(f"CHPM {kind} motives repeat or reference unavailable sources.")
        resolved = [
            ResolvedMotive(
                source=catalogue.sources[m.motive_id], effect=m.effect, relevance=m.relevance
            )
            for m in candidate.motives
        ]
        if not any(_own_support(motive, catalogue.observer_id) for motive in resolved):
            raise ChpmError(f"CHPM {kind} lacks a supporting character or active agenda motive.")
        alignment = candidate.goal_alignment
        if alignment in {"supports", "conflicts"} and not any(
            motive.source.kind == "authored_goal"
            and candidate.goal_quote
            and candidate.goal_quote in motive.source.text
            and motive.effect == ("supports" if alignment == "supports" else "tension")
            for motive in resolved
        ):
            raise ChpmError(f"CHPM {kind} goal alignment disagrees with its cited motive.")
        result[kind] = resolved
    return result


def _own_support(motive: ResolvedMotive, actor: str) -> bool:
    return (
        motive.effect == "supports"
        and motive.source.subject_id == actor
        and motive.source.status in {"authored", "declared"}
    )


INSTRUCTIONS = """
MOTIVES: For EACH candidate return motives (1-3), before any action is selected.
Each motive contains motive_id from motivation_context.sources, effect (supports
or tension), and one short relevance statement linking that source to this specific
intention. These are fallible proposed reasons, not a private reasoning transcript.
Sources with appraisal_ref refer to visible_evidence or existing_beliefs in
appraisal_context; their text is not repeated in the motivation catalogue.
At least one supports motive must be this NPC's authored character, trait, value,
role, goal or active declared agenda. A player's request/report alone is not a
personal motive; acceptance is valid when it also serves this character. Refusal
is not automatically more independent. Do not invent a motive to justify compliance.
Keep competing pressures visible: a conflicting authored goal needs a tension
motive plus support from another character/agenda source. For goal_alignment
supports/conflicts, cite the authored_goal source containing goal_quote with the
corresponding supports/tension effect. Other sources do not prove goal alignment.
Traits are contextual tendencies, not absolute bans or commands; do not force
opposite personalities into the same response or require them always to disagree.
Active commitments are declared intentions, not completed actions or immutable duties.
Reports remain reports, challenged beliefs remain disputed, and neither rewrites
identity. Newly proposed interpretations are tentative context, not new source IDs.
Do not cite absent/closed agenda entries or another observer's private knowledge.
Do not manufacture emotions, desires or memories merely to complete this schema.
"""
