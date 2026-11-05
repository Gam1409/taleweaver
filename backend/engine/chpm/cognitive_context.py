"""Fit optional historical views without dropping identity or changing saved budgets."""

from backend.engine.chpm import appraisal_context, experience, inference, motivation
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaEntry, Observation, Settings

# recent sources, old excerpt characters, recall fragments, beliefs, dialogue window
TIERS = ((6, 1000, 3, 8, 24), (6, 600, 2, 6, 6), (4, 300, 1, 4, 2), (4, 300, 0, 2, 0))


def pack(
    mind: Mind,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    settings: Settings,
    instruction: str,
) -> tuple[appraisal_context.Window, motivation.Catalogue, dict, dict]:
    cues = " ".join(
        source.text
        for source in mind.sources.values()
        if source.message_id == observation.message_id and source.kind in {"speech", "world_event"}
    )
    size = 0
    for index, (recent, chars, recall, beliefs, dialogue) in enumerate(TIERS):
        window = appraisal_context.build(
            mind,
            query=cues,
            recent_limit=recent,
            excerpt_chars=chars,
            recall_limit=recall,
            belief_limit=beliefs,
            current_message_id=observation.message_id,
        )
        catalogue = motivation.build(mind, entries, window)
        ids = window.identifiers()
        ids["motive_id"] = list(catalogue.sources)
        goals = mind.genesis.identity.authored_goals
        if all(len(goal) <= 300 for goal in goals):
            ids["goal_quote"] = ["", *goals]
        payload = _payload(mind, supplied, window, catalogue, index, dialogue)
        system, content = inference.compose(instruction, payload, GroundedProposal, ids)
        size = len(system) + len(content)
        if size <= settings.max_input_chars:
            return window, catalogue, payload, ids
    raise ChpmError(
        f"CHPM required context exceeds its budget ({size} > {settings.max_input_chars} characters). No request was sent; increase the input limit explicitly."
    )


def _payload(
    mind: Mind,
    supplied: dict,
    window: appraisal_context.Window,
    catalogue: motivation.Catalogue,
    tier: int,
    dialogue: int,
) -> dict:
    previous = supplied.get("witnessed_utterances_not_world_facts", [])
    kept = previous[-dialogue:] if dialogue else []
    return {
        **supplied,
        "witnessed_utterances_not_world_facts": kept,
        "appraisal_context": window.payload,
        "motivation_context": catalogue.payload(),
        "experience_context": experience.view(mind),
        "context_packing": {
            "policy": "historical-view-budget-v1",
            "tier": tier,
            "dialogue_entries_omitted": len(previous) - len(kept),
            "canonical_history_changed": False,
        },
    }
