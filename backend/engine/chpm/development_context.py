"""Slow development uses dated, observer-local episodes, never a player's trait command."""

from dataclasses import dataclass

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


def episodes(mind: Mind) -> dict[str, Episode]:
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
        indices = sorted(
            {round(i * (len(available) - 1) / (SOURCE_LIMIT - 1)) for i in range(SOURCE_LIMIT)}
        )
        available = [available[index] for index in indices]
    return {f"d{index}": item for index, item in enumerate(available, 1)}


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
