"""Build the observer's bounded lookup context for either tool protocol."""

from backend.engine.chpm import (
    agent_beliefs,
    agent_observable,
    continuation,
    host_observations,
    narrative_context,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import Observation


def build(
    mind: Mind,
    observation: Observation,
    supplied: dict,
    tools: Tools,
    remaining_rounds: int,
    previous_lookups: list[dict],
) -> dict:
    facts = host_observations.previous(mind)
    return {
        "observer_id": mind.genesis.scope.observer_id,
        "identity": mind.genesis.identity.model_dump(mode="json"),
        "observation": observation.model_dump(),
        "current_state": {
            key: value
            for key, value in supplied.get("psychological_state", {}).items()
            if key != "belief_context_ref"
        },
        "experience_context": narrative_context.experience_reasons(
            mind,
            continuation.experience_view(mind, supplied.get("_chpm_gap_cursors", {})),
        ),
        **agent_beliefs.subject_view(tools.mind),
        **agent_observable.index(tools),
        "agenda": supplied.get("declared_agenda_not_world_facts", []),
        **(
            {"causal_continuity_not_world_facts": supplied["causal_continuity_not_world_facts"]}
            if supplied.get("causal_continuity_not_world_facts")
            else {}
        ),
        "visible_clothing_actors": {
            key: value["name"]
            for key, value in tools.clothing.items()
            if facts and key in facts.visible_actor_ids
        },
        "remaining_rounds": remaining_rounds,
        "max_tool_calls_per_round": 2,
        "previous_lookups": previous_lookups,
        **({"personal_notebook": tools.notebook.metadata()} if tools.notebook else {}),
        **({"pending_actions_not_world_facts": tools.actions.context()} if tools.actions else {}),
    }
