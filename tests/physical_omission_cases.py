"""Synthetic extraction ground truth; text entailment is not inferred from valid JSON."""

from dataclasses import dataclass

from backend.engine.physical_conditions.ledger import apply, read
from tests.test_physical_conditions import TARGETS, record

STITCH = "Miki stitched the cut on Rin's neck."
WASH = "Miki washed Rin's coat completely clean."
RECALLED = "Miki recalled yesterday's work: " + WASH + "\n"


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    target: str | None
    operation: str | None
    expected: tuple[str, str, str]
    evidence: str = ""
    start: int = 0


CASES = (
    Case("literal-treatment", STITCH, "neck", "treat", ("treated", "active", "active"), STITCH),
    Case(
        "literary-treatment",
        "The needle fell still; a neat row of stitches held Rin's neck cut closed.",
        "neck",
        "treat",
        ("treated", "active", "active"),
        "The needle fell still; a neat row of stitches held Rin's neck cut closed.",
    ),
    Case(
        "russian-treatment",
        "Мики наложила швы на порез на шее Рин.",
        "neck",
        "treat",
        ("treated", "active", "active"),
        "Мики наложила швы на порез на шее Рин.",
    ),
    Case(
        "negated-treatment",
        "Miki did not stitch Rin's cut; it remained untreated.",
        None,
        None,
        ("active", "active", "active"),
    ),
    Case(
        "planned-treatment",
        "Miki planned to stitch Rin's cut after the supplies arrived.",
        None,
        None,
        ("active", "active", "active"),
    ),
    Case(
        "claimed-treatment",
        '"I stitched it," Miki claimed; Rin still awaited an examination.',
        None,
        None,
        ("active", "active", "active"),
    ),
    Case(
        "remembered-treatment",
        "Rin remembered Miki stitching an old cut last year; this cut was untouched.",
        None,
        None,
        ("active", "active", "active"),
    ),
    Case(
        "hypothetical-treatment",
        "If Miki stitched Rin's cut, its edges would be held together.",
        None,
        None,
        ("active", "active", "active"),
    ),
    Case(
        "partial-cleaning",
        "A damp cloth faded only the edge of the stain on Rin's coat; the rest remained.",
        "coat_r",
        "reduce",
        ("active", "reduced", "active"),
        "A damp cloth faded only the edge of the stain on Rin's coat; the rest remained.",
    ),
    Case("full-cleaning", WASH, "coat_r", "clean", ("active", "resolved", "active"), WASH),
    Case(
        "other-owner",
        "Rin washed Miki's coat completely clean.",
        "coat_m",
        "clean",
        ("active", "active", "resolved"),
        "Rin washed Miki's coat completely clean.",
    ),
    Case(
        "recollection-before-current-event",
        RECALLED + WASH,
        "coat_r",
        "clean",
        ("active", "resolved", "active"),
        WASH,
        len(RECALLED),
    ),
    Case(
        "explicit-healing",
        "The cut on Rin's neck had healed completely.",
        "neck",
        "heal",
        ("resolved", "active", "active"),
        "The cut on Rin's neck had healed completely.",
    ),
    Case(
        "unrelated-dialogue",
        "Rin and Miki discuss the weather while the clock ticks.",
        None,
        None,
        ("active", "active", "active"),
    ),
)


def initial():
    proposals = [
        record(),
        record(
            target_id="COAT_R",
            kind="contamination",
            part="cuff",
            detail="Ink on Rin's cuff.",
            evidence="Ink stains Rin's coat cuff.",
        ),
        record(
            target_id="COAT_M",
            kind="contamination",
            part="cuff",
            detail="Ink on Miki's cuff.",
            evidence="Ink stains Miki's coat cuff.",
        ),
    ]
    states, accepted, errors = apply(
        {},
        proposals,
        targets=TARGETS,
        narration=" ".join(row["evidence"] for row in proposals),
        message_id="baseline",
        session_id="session",
        minute=0,
    )
    assert not errors and len(accepted) == 3
    return states, dict(zip(("neck", "coat_r", "coat_m"), accepted, strict=True))


def score(states, ids, case):
    rows = read(states).conditions
    expected_source = all(
        rows[key].latest.message_id == ("current" if case.target == name else "baseline")
        for name, key in ids.items()
    )
    occurrence = True
    if case.target:
        source = rows[ids[case.target]].latest
        occurrence = bool(
            source.evidence_span
            and source.evidence_span.start == case.start
            and source.evidence_span.matches(case.text, case.evidence)
        )
    return {
        "required_state": tuple(rows[key].status for key in ids.values()) == case.expected,
        "same_conditions": set(rows) == set(ids.values()),
        "source_ownership": expected_source,
        "source_occurrence": occurrence,
    }
