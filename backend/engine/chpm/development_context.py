"""Slow development uses dated, observer-local episodes, never a player's trait command."""

from dataclasses import dataclass

from backend.engine.chpm.belief_recall import words
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.history import events
from backend.engine.chpm.host_observations import previous
from backend.engine.chpm.host_state import Mind, Source, fingerprint

PREFIX = "development."
DAY = 1440
TRAIT_SPAN = 7 * DAY
SOURCE_LIMIT = 9


@dataclass(frozen=True)
class Episode:
    record_id: str
    source: Source
    minute: int
    scene: str
    excerpt: str


def episodes(
    mind: Mind, *, query: str = "", focus_subjects: tuple[str, ...] = ()
) -> dict[str, Episode]:
    scene = None
    times = {event.event_id: event.sim_minute for event in events(mind.snapshot)}
    available = []
    for evidence in mind.snapshot.evidence:
        source = mind.sources.get(evidence.event_id)
        if source and source.kind == "host_frame":
            scene = source.facts.scene_id if source.facts else None
        if not source or source.kind != "speech" or scene is None:
            continue
        available.append(
            Episode(evidence.id, source, times[evidence.event_id], scene, source.text[:200])
        )
    if len(available) > SOURCE_LIMIT:
        available = _sample(available, mind.genesis.scope.observer_id, query, focus_subjects)
    return {f"d{index}": item for index, item in enumerate(available, 1)}


def _dated(entries: list[Episode]) -> list[Episode]:
    unique = list({e.source.message_id: e for e in entries}.values())
    if len(unique) <= 3:
        return unique
    first, last = unique[0], unique[-1]
    others = [e for e in unique[1:-1] if e.scene not in {first.scene, last.scene}]
    middle = (others or unique[1:-1])[len(others or unique[1:-1]) // 2]
    return [first, middle, last]


def _sample(
    entries: list[Episode], observer: str, query: str, subjects: tuple[str, ...]
) -> list[Episode]:
    own = [e for e in entries if e.source.speaker_id == observer and e.source.role == "assistant"]
    selected = {e.record_id: e for e in _dated(own)}
    subject = next((s for s in subjects if s != observer), "@player")
    selected.update(
        {e.record_id: e for e in _dated([e for e in entries if e.source.speaker_id == subject])}
    )
    cues = words(query)
    order = {e.record_id: index for index, e in enumerate(entries)}
    ranked = sorted(
        entries, key=lambda e: (len(cues & words(e.excerpt)), order[e.record_id]), reverse=True
    )
    for entry in ranked:
        if len(selected) >= SOURCE_LIMIT:
            break
        selected.setdefault(entry.record_id, entry)
    return sorted(selected.values(), key=lambda e: order[e.record_id])


def spans(entries: list[Episode], minimum: int) -> bool:
    messages = {item.source.message_id for item in entries}
    return (
        len(messages) >= 3
        and max((e.minute for e in entries), default=0)
        - min((e.minute for e in entries), default=0)
        >= minimum
    )


def eligible(mind: Mind, available: dict[str, Episode]) -> bool:
    own = [e for e in available.values() if e.source.speaker_id == mind.genesis.scope.observer_id]
    if spans(own, DAY):
        return True
    speakers = {item.source.speaker_id for item in available.values()}
    return any(
        spans([e for e in available.values() if e.source.speaker_id == speaker], DAY)
        for speaker in speakers
    )


def scene_key(scene: str) -> str:
    return fingerprint({"scene": scene})[:16]


def tendencies(mind: Mind) -> list[dict]:
    frame = previous(mind)
    latest: dict[tuple[str, str], dict] = {}
    for belief in relationships.recent(mind.snapshot, len(mind.snapshot.beliefs)):
        if not belief.domain.startswith(PREFIX):
            continue
        kind, separator, qualifier = belief.domain[len(PREFIX) :].partition(".")
        if not separator or kind not in {"habit", "relationship", "trait"}:
            continue
        if kind == "habit" and (not frame or qualifier != scene_key(frame.scene_id)):
            continue
        latest[belief.domain, belief.about_id] = {
            "development_id": belief.id,
            "kind": kind,
            "qualifier": qualifier,
            "about_id": belief.about_id,
            "tendency": belief.statement,
            "status": "contested" if belief.status == "challenged" else "tentative",
            "original_identity_changed": False,
        }
    return list(latest.values())[-4:]


def payload(mind: Mind, available: dict[str, Episode]) -> dict:
    return {
        "policy": "slow-tendencies-v1",
        "current_tendencies": tendencies(mind),
        "basis": [
            {
                "episode_id": alias,
                "speaker_id": e.source.speaker_id,
                "scene_id": e.scene,
                "minute": e.minute,
                "text": e.excerpt,
                "kind": "reported_speech_not_world_outcome",
            }
            for alias, e in available.items()
        ],
        "scope": "conversational habits, directed expectations and qualitative trait tendencies",
        "minimum_span_minutes": {"habit": DAY, "relationship": DAY, "trait": TRAIT_SPAN},
        "sampling": "up to 9 chronological source samples; omissions are not absence of events",
    }
