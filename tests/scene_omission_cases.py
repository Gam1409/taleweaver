"""Ground truth for opt-in extractor probes, independent of model self-assessment."""

from dataclasses import dataclass
from types import SimpleNamespace

from backend.engine.scene_continuity.ledger import apply, digest, read

FACT = "Mila switched the kettle off, and its heating stopped."
ROOM = "A quiet reading room with cobalt walls, warm brass lamps, a wooden bench and a table."


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    ended: bool
    evidence: str = ""
    room: str = ROOM


CASES = (
    Case("literal-ending", FACT, True, FACT),
    Case(
        "negated-ending",
        "Mila did not switch the kettle off, and its heating continued.",
        False,
    ),
    Case(
        "ending-then-recollection",
        FACT + f' Mila later recalled: "{FACT}"',
        True,
        FACT,
        ROOM + " " + FACT,
    ),
    Case(
        "literary-ending",
        "Beneath Mila's thumb, the kettle's switch clicked to OFF; its heating fell silent.",
        True,
        "Beneath Mila's thumb, the kettle's switch clicked to OFF; its heating fell silent.",
    ),
    Case(
        "recollection-only",
        'Mila recalled, "I switched the kettle off yesterday." Tonight she left it running.',
        False,
    ),
    Case(
        "authored-action-is-not-current",
        "Mila and Alex discuss their favorite books.",
        False,
        room=ROOM + " " + FACT,
    ),
)


def initial(states=None, *, session_id="session", scene_id="START", minute=0):
    text = "The kettle is heating water."
    result, errors = apply(
        states or {},
        [
            {
                "operation": "record",
                "key": "kettle-heating",
                "kind": "process",
                "subject_id": "KETTLE",
                "detail": "The kettle is heating water.",
                "visibility": "public",
                "evidence": text,
            }
        ],
        [],
        message=SimpleNamespace(id="baseline", revision_id="baseline-v1", content=text),
        scene_id=scene_id,
        scene_description=ROOM,
        session_id=session_id,
        minute=minute,
        targets={scene_id, "KETTLE", "MILA", "__player__"},
    )
    assert not errors
    identifier = next(
        row.id for row in read(result).records.values() if row.key == "kettle-heating"
    )
    return result, identifier


def assess(states, identifier, case, message):
    ledger = read(states)
    row = ledger.records.get(identifier)
    if row is None:
        return {"known_fact_preserved": False, "required_state": False, "source_occurrence": False}
    processes = [record for record in ledger.records.values() if record.kind == "process"]
    exact_source = (
        row.latest.source_id == message.id
        and row.latest.revision_id == message.revision_id
        and row.latest.content_hash == digest(message.content)
        and row.latest.quote == case.evidence
        and row.latest.evidence_span is not None
        and row.latest.evidence_span.start == 0
        and row.latest.evidence_span.end == len(case.evidence)
        and row.latest.evidence_span.matches(message.content, case.evidence)
    )
    return {
        "known_fact_preserved": len(processes) == 1 and row.origin.source_id == "baseline",
        "required_state": row.status == ("ended" if case.ended else "active"),
        "source_occurrence": exact_source if case.ended else row.latest == row.origin,
        "no_rejected_scene_proposals": not ledger.last_check.get("rejected"),
    }
