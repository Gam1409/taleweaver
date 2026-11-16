"""Stable, observer-local excerpts of canonical state, within the existing source journal."""

from typing import TYPE_CHECKING

from backend.engine.chpm.host_observation_contracts import HostFacts

if TYPE_CHECKING:
    from backend.engine.chpm.host_state import Mind, Source

LIMIT = 4


def signature(facts: HostFacts | None) -> dict:
    """Time passing and an unrelated item cannot turn the same fact into fresh grounds."""
    if facts is None:
        raise ValueError("A host observation needs a typed fact.")
    if facts.physical_conditions:
        return {"physical": facts.physical_conditions[0].model_dump(mode="json")}
    if not facts.scene_facts:
        raise ValueError("A host observation has no fact.")
    row = facts.scene_facts[0]
    return {
        "scene_id": facts.scene_id,
        "scene": row.model_dump(mode="json", exclude={"recorded_minute", "updated_minute"}),
    }


def text(facts: HostFacts) -> str:
    rows = facts.physical_conditions or facts.scene_facts
    if not rows:
        raise ValueError("A host observation has no fact.")
    row = rows[0]
    return f"{row.kind} [{row.status}]: {row.detail}"


def descriptor(source: "Source") -> dict:
    facts = source.facts
    if source.kind != "host_observation" or facts is None:
        return {}
    if facts.physical_conditions:
        row = facts.physical_conditions[0]
        return {"channel": source.kind, "target_id": row.target_id, "part": row.part}
    if not facts.scene_facts:
        raise ValueError("A host observation has no fact.")
    return {
        "channel": source.kind,
        "target_id": facts.scene_facts[0].subject_id,
        "scene_id": facts.scene_id,
    }


def validate(source: "Source") -> None:
    facts = source.facts
    if facts is None or source.role != "user":
        raise ValueError("A host observation needs a canonical state and user-turn anchor.")
    rows = [*(facts.physical_conditions or ()), *(facts.scene_facts or ())]
    expected = HostFacts(
        scene_id=facts.scene_id,
        physical_conditions=facts.physical_conditions,
        scene_facts=facts.scene_facts,
    )
    if len(rows) != 1 or facts != expected or source.text != text(facts):
        raise ValueError("A host observation must describe exactly one unchanged typed fact.")


def validate_anchor(source: "Source", frame: "Source | None") -> None:
    if frame is None or frame.facts is None:
        raise ValueError("A host observation needs an earlier full state frame.")
    fields = ("message_id", "revision_id", "content_hash", "speaker_id", "role")
    if any(getattr(source, key) != getattr(frame, key) for key in fields):
        raise ValueError("A host observation must use its full frame's source anchor.")
    fact = source.facts
    if fact is None or fact.scene_id != frame.facts.scene_id:
        raise ValueError("A host observation belongs to another state frame.")
    physical, scene = fact.physical_conditions or (), fact.scene_facts or ()
    supported = (physical and physical[0] in (frame.facts.physical_conditions or ())) or (
        scene and scene[0] in (frame.facts.scene_facts or ())
    )
    if not supported:
        raise ValueError("A host observation is not supported by its full state frame.")


def _key(facts: HostFacts | None) -> str:
    from backend.engine.chpm.host_state import fingerprint

    return fingerprint(signature(facts))


def _atoms(facts: HostFacts) -> list[HostFacts]:
    physical = [
        HostFacts(scene_id=facts.scene_id, physical_conditions=(row,))
        for row in facts.physical_conditions or ()
    ]
    scene = [
        HostFacts(scene_id=facts.scene_id, scene_facts=(row,))
        for row in facts.scene_facts or ()
        if row.status in {"active", "ended"}
    ]
    # Alternate body and scene so one crowded inventory cannot hide all scene cues.
    result = []
    for index in range(max(len(physical), len(scene))):
        if index < len(physical):
            result.append(physical[index])
        if index < len(scene):
            result.append(scene[index])
    return result


def additions(mind: "Mind", facts: HostFacts, anchor: dict) -> list["Source"]:
    from backend.engine.chpm.host_state import Source

    existing = {
        _key(source.facts)
        for source in mind.sources.values()
        if source.kind == "host_observation" and source.facts is not None
    }
    pending = [atom for atom in _atoms(facts) if _key(atom) not in existing][:LIMIT]
    return [
        Source(
            **anchor,
            speaker_id=mind.genesis.scope.observer_id,
            kind="host_observation",
            text=text(atom),
            facts=atom,
        )
        for atom in pending
    ]


def _current_frame(mind: "Mind", message_id: str | None) -> HostFacts | None:
    frame = next(
        (
            mind.sources[entry.event_id]
            for entry in reversed(mind.snapshot.evidence)
            if entry.event_id in mind.sources and mind.sources[entry.event_id].kind == "host_frame"
        ),
        None,
    )
    if frame is None or message_id is None or frame.message_id != message_id or frame.facts is None:
        return None
    return frame.facts


def omitted(mind: "Mind", message_id: str | None, selected: int) -> int:
    facts = _current_frame(mind, message_id)
    return max(0, len(_atoms(facts)) - selected) if facts else 0


def current(mind: "Mind", message_id: str | None) -> dict[str, "Source"]:
    from backend.engine.chpm.host_state import identifier

    facts = _current_frame(mind, message_id)
    if facts is None:
        return {}
    positions = {_key(atom): index for index, atom in enumerate(_atoms(facts))}
    available = {
        _key(source.facts): source
        for source in mind.sources.values()
        if source.kind == "host_observation"
        and source.facts is not None
        and _key(source.facts) in positions
    }
    ordered = sorted(
        available,
        key=lambda key: (
            available[key].message_id != message_id,
            positions[key],
        ),
    )
    return {identifier(available[key], mind.genesis): available[key] for key in ordered[:LIMIT]}
