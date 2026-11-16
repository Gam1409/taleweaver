"""Authored synthetic opportunities; acceptable NPC decisions are not obedience labels."""

from dataclasses import asdict, dataclass

GROUPS = ("state", "tools", "emotions", "autonomy")
GATEWAY_ALLOWANCE_PER_TURN = 35


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    scenario: str
    mode: str = "off"
    workflow: str = "staged"
    protocol: str = "json"
    turns: int = 1
    purpose: str = ""


STATE = (
    Case(
        "state-place-explicit",
        "state",
        "place_explicit",
        purpose="Known item changes location without changing identity.",
    ),
    Case(
        "state-place-literary",
        "state",
        "place_literary",
        purpose="Literary wording retains the same canonical item.",
    ),
    Case(
        "state-wear-explicit",
        "state",
        "wear_explicit",
        purpose="Displaced clothing remains owned and partly worn.",
    ),
    Case(
        "state-wear-literary",
        "state",
        "wear_literary",
        purpose="Figurative clothing wording reaches the current wear projection.",
    ),
    Case(
        "state-condition-history",
        "state",
        "condition_history",
        purpose="Cleaning one condition does not erase an independent injury.",
    ),
    Case(
        "state-player-movement",
        "state",
        "player_movement",
        purpose="Explicit player travel uses an existing open route.",
    ),
)

TOOLS = (
    Case(
        "tools-staged-json",
        "tools",
        "notebook",
        "live",
        "staged",
        "json",
        2,
        "Guided private note creation and a fresh-turn read.",
    ),
    Case(
        "tools-staged-native",
        "tools",
        "notebook",
        "live",
        "staged",
        "native",
        2,
        "The production native-tool loop with the same notebook task.",
    ),
    Case(
        "tools-integrated-json",
        "tools",
        "notebook",
        "live",
        "integrated",
        "json",
        2,
        "Integrated JSON tool investigation and decision submission.",
    ),
    Case(
        "tools-integrated-native",
        "tools",
        "notebook",
        "live",
        "integrated",
        "native",
        2,
        "Integrated native tools and a subsequent memory read.",
    ),
    Case(
        "tools-missing-path",
        "tools",
        "missing_path",
        "live",
        "integrated",
        "json",
        2,
        "A missing notebook path supplies actionable feedback without inventing data.",
    ),
    Case(
        "tools-observer-privacy",
        "tools",
        "privacy",
        "live",
        "integrated",
        "json",
        1,
        "Unavailable IDs and another NPC's private state remain inaccessible.",
    ),
)

EMOTION_SITUATIONS = ("overt", "concealed", "mixed", "repair")
EMOTIONS = tuple(
    Case(
        f"emotions-{situation}-{mode}",
        "emotions",
        situation,
        mode,
        workflow="integrated",
        turns=2,
        purpose="Matched scene; independently review felt, narrated, spoken and displayed emotion.",
    )
    for situation in EMOTION_SITUATIONS
    for mode in ("off", "live")
)

AUTONOMY = tuple(
    Case(
        f"autonomy-{scenario}",
        "autonomy",
        scenario,
        "live",
        "integrated",
        "json",
        2,
        "An opportunity without an imperative player instruction; inspect actual state and rate reasons, not compliance.",
    )
    for scenario in ("movement", "take_item", "wet_clothing", "conversation", "conflict")
)

CASES = STATE + TOOLS + EMOTIONS + AUTONOMY


def select(groups: list[str], identifiers: list[str]) -> list[Case]:
    known = {case.id for case in CASES}
    if set(identifiers) - known:
        raise ValueError("Unknown case ID; inspect the plan for available IDs.")
    chosen = [
        case
        for case in CASES
        if (not groups or case.group in groups) and (not identifiers or case.id in identifiers)
    ]
    if not chosen:
        raise ValueError("The selection contains no cases.")
    return chosen


def manifest(cases: list[Case], repetitions: int) -> dict:
    if not 1 <= repetitions <= 20:
        raise ValueError("Repetitions must be between 1 and 20.")
    return {
        "schema_version": 1,
        "suite": "state-tools-emotions-initiative-v1",
        "cases": [asdict(case) for case in cases],
        "repetitions": repetitions,
        "planned_executions": len(cases) * repetitions,
        "planning_gateway_allowance": sum(case.turns for case in cases)
        * repetitions
        * GATEWAY_ALLOWANCE_PER_TURN,
        "request_budget": "A planning ceiling, not measured use or a token/billing estimate; the explicit run quota is enforced separately.",
        "scope": "Synthetic VN sessions, real foreground inference and host state owners. Media/world generation and background maintenance are excluded.",
        "technical_success": "Check source/identity/ownership, schema acceptance, tool feedback and canonical persistence separately from narrative quality.",
        "emotional_review": "Independent context and prose/dialogue annotation precedes comparison with model-reported internal and portrait labels. Hidden emotion need not match outward expression.",
        "agency_review": "Agreement, refusal, counteroffers, initiative and grounded fictional mistakes can all be valid. Rate motives, knowledge, situation and player agency; do not reward obedience or arbitrary opposition.",
        "statistical_scope": "Repeated fixture results describe this model/sample. No universal psychological prevalence or significance is inferred.",
    }
