"""Source-bound qualitative experiences, separate from traits and relationship beliefs."""

from .contracts import Evidence, Experience, ExperienceState, Snapshot
from .errors import TransitionError
from .limits import MAX_EXPERIENCES


def project(
    snapshot: Snapshot, body: Experience, *, event_id: str, minute: int
) -> tuple[tuple[Evidence, ...], tuple[ExperienceState, ...], tuple[str, ...]]:
    if body.identity_revision != snapshot.genesis.identity.source_revision:
        raise TransitionError("Experience is grounded in a different psychological identity.")
    evidence = {item.id: item for item in snapshot.evidence}
    roots: set[str] = set()
    for citation in body.citations:
        source = evidence.get(citation.record_id)
        if source is None or citation.quote not in source.text:
            raise TransitionError("Experience citation is unavailable or inexact.")
        roots.update(source.root_ids)
    key = (body.channel, body.dimension, body.about_id)
    previous = next((item for item in snapshot.experiences if identity(item) == key), None)
    if previous is None and len(snapshot.experiences) >= MAX_EXPERIENCES:
        raise TransitionError(
            "Experience capacity reached; existing dimensions can still be revised."
        )
    if previous and roots <= set(evidence[previous.record_id].root_ids):
        raise TransitionError("Repeated grounds cannot refresh or intensify an experience.")
    item = Evidence(
        id=body.record_id,
        text=body.explanation,
        source_kind="inference",
        root_ids=tuple(sorted(roots)),
        citations=body.citations,
        event_id=event_id,
        alternatives=body.alternatives,
        unknowns=body.unknowns,
    )
    state = ExperienceState(
        channel=body.channel,
        dimension=body.dimension,
        about_id=body.about_id,
        level=body.level,
        record_id=body.record_id,
        sim_minute=minute,
    )
    retained = tuple(item for item in snapshot.experiences if identity(item) != key)
    old_roots = set(evidence[previous.record_id].root_ids) if previous else set()
    return (*snapshot.evidence, item), (*retained, state), tuple(sorted(roots - old_roots))


def identity(value: ExperienceState) -> tuple[str, str, str | None]:
    return value.channel, value.dimension, value.about_id
