"""Fit optional historical views without dropping identity or changing saved budgets."""

from backend.engine.chpm import appraisal_context, experience, inference, motivation
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaEntry, Observation, Settings

# recent sources, old excerpt characters, recall fragments, beliefs, dialogue window
TIERS = ((6, 1000, 3, 8, 24), (6, 600, 2, 6, 6), (4, 300, 1, 4, 2), (4, 300, 0, 2, 0))


class ContextBudgetError(ChpmError):
    """Required views do not fit the configured request size."""


def pack(
    mind: Mind,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    settings: Settings,
    instruction: str,
    *,
    schema: type[GroundedProposal] = GroundedProposal,
    extra: dict | None = None,
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
        ids["personal_motive_ids"] = [
            key
            for key, source in catalogue.sources.items()
            if source.status in {"authored", "declared"}
            and source.subject_id == catalogue.observer_id
        ]
        development = (extra or {}).get("development_context", {})
        ids["episode_id"] = [item["episode_id"] for item in development.get("basis", [])]
        ids["trait_key"] = [trait.key for trait in mind.genesis.identity.traits]
        ids["existing_id"] = [
            item["development_id"] for item in development.get("current_tendencies", [])
        ]
        goals = mind.genesis.identity.authored_goals
        if all(len(goal) <= 300 for goal in goals):
            ids["goal_quote"] = ["", *goals]
        payload = _payload(mind, supplied, window, catalogue, index, dialogue)
        payload.update(extra or {})
        system, content = inference.compose(instruction, payload, schema, ids)
        size = len(system) + len(content)
        if size <= settings.max_input_chars:
            return window, catalogue, payload, ids
    raise ContextBudgetError(
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
