"""Fixed-candidate counterfactuals isolate motive arbitration from prose generation."""

from backend.engine.chpm import initiative, preference
from backend.engine.chpm.motivation_contracts import MotiveSource, ResolvedMotive
from backend.engine.chpm.schema import Decision, Proposal
from tests.test_chpm_initiative import GOAL, candidate, gate
from tests.test_chpm_kernel import observation


def motive(text="Keep a promise", effect="supports", status="declared", key="promise"):
    return ResolvedMotive(
        source=MotiveSource(
            id=key,
            kind="commitment" if status == "declared" else "report",
            text=text,
            provenance_id=key,
            subject_id="npc" if status == "declared" else "@player",
            status=status,
        ),
        effect=effect,
        relevance="Relevant to this alternative",
    )


def choose(motives, kinds=("ACCEPT", "REFUSE"), question=None):
    return initiative.select(
        "npc",
        observation(),
        Proposal(candidates=[candidate(k) for k in kinds], appraisal="test"),
        question,
        goal=GOAL,
        context_hash="context",
        motives=motives,
    )


def test_same_options_choose_the_one_without_avoidable_personal_tension():
    base = [motive()]
    tension = motive("Compromise professional duty", "tension", key="duty")
    first = choose({"ACCEPT": base, "REFUSE": [*base, tension]})
    second = choose({"ACCEPT": [*base, tension], "REFUSE": base})
    assert first.selected.kind == "ACCEPT"
    assert second.selected.kind == "REFUSE"
    assert first.motive_dominance == {"ACCEPT": [], "REFUSE": ["ACCEPT"]}
    assert first.policy_version == "motive-frontier-v1"
    assert Decision.model_validate_json(first.model_dump_json()) == first


def test_tradeoffs_are_incomparable_and_reports_are_not_extra_votes():
    motives = {
        "ACCEPT": [motive("Duty", key="duty")],
        "REFUSE": [motive("Autonomy", key="autonomy")],
    }
    compared = preference.compare([candidate("ACCEPT"), candidate("REFUSE")], motives)
    assert compared == {"ACCEPT": [], "REFUSE": []}
    equal = {"ACCEPT": [motive()], "REFUSE": [motive(), motive("Please obey", status="reported")]}
    assert preference.compare([candidate("ACCEPT"), candidate("REFUSE")], equal) == compared


def test_duplicate_aliases_cannot_multiply_a_personal_motive():
    first = motive()
    alias = first.model_copy(update={"source": first.source.model_copy(update={"id": "alias"})})
    compared = preference.compare(
        [candidate("ACCEPT"), candidate("REFUSE")], {"ACCEPT": [first], "REFUSE": [first, alias]}
    )
    assert not any(compared.values())


def test_motives_do_not_bypass_question_gate_or_conditionally_unavailable_actions():
    motives = {kind: [motive()] for kind in ("CLARIFY", "ACCEPT", "REFUSE", "INITIATE")}
    motives["ACCEPT"].append(motive("Useful extra commitment", key="extra"))
    result = choose(motives, tuple(motives), gate())
    assert result.selected.kind == "INITIATE"
    assert result.motive_dominance == {"INITIATE": []}
    unsupported = choose({"CLARIFY": [motive()], "ACCEPT": [motive()]}, ("CLARIFY", "ACCEPT"))
    assert unsupported.selected.kind == "ACCEPT"
