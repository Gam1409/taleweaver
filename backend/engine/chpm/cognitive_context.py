"""Fit optional historical views without dropping identity or changing saved budgets."""

import json

from pydantic import BaseModel

from backend.engine.chpm import (
    agenda_references,
    appraisal_context,
    continuation,
    inference,
    motivation,
    narrative_context,
    proposal_references,
    quote_references,
)
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.core.contracts import Belief
from backend.engine.chpm.development_context import Episode
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind, Source
from backend.engine.chpm.notebook_tools import packed_context
from backend.engine.chpm.schema import AgendaEntry, Observation, Settings

# recent sources, old excerpt characters, recall fragments, beliefs, dialogue window
TIERS = ((6, 1000, 3, 8, 24), (6, 600, 2, 6, 6), (4, 300, 1, 4, 2), (4, 300, 0, 2, 0))


class ContextBudgetError(RecoverableChpmError):
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
    pinned: dict[str, tuple[str, Source, str]] | None = None,
    pinned_beliefs: dict[str, Belief] | None = None,
    focus_subjects: tuple[str, ...] = (),
    wire_schema: type[BaseModel] | None = None,
    reference_episodes: dict[str, Episode] | None = None,
    reference_binding: dict | None = None,
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
            pinned=pinned,
            pinned_beliefs=pinned_beliefs,
            focus_subjects=focus_subjects,
        )
        catalogue = motivation.build(mind, entries, window)
        ids = window.identifiers()
        ids.update(catalogue.identifiers())
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
        if wire_schema is not None and issubclass(wire_schema, proposal_references.ReferenceDraft):
            references = quote_references.build(
                window,
                catalogue,
                reference_episodes or {},
                binding={
                    "observation": observation.model_dump(exclude={"player_request"}),
                    "control": reference_binding or {},
                },
            )
            payload = references.project(payload)
            ids["fragment_id"] = list(references.quotes)
            ids["reference_scope"] = [references.scope]
            ids["entry_id"] = agenda_references.active_ids(entries, catalogue.observer_id)
        if "previous_intention" in payload and payload["previous_intention"] is None:
            ids["continuity"] = ["new"]
            ids["change_basis"] = []
        system, content = inference.compose(instruction, payload, wire_schema or schema, ids)
        size = len(system) + len(content)
        if size <= settings.max_input_chars:
            return window, catalogue, payload, ids
    raise ContextBudgetError(
        f"CHPM required context exceeds its budget ({size} > {settings.max_input_chars} characters). No request was sent for the decision proposal; increase the input limit explicitly."
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
    actions = supplied.get("own_action_observations_not_world_facts", [])
    kept_actions = actions[-dialogue:] if dialogue else []
    result = {
        **{key: value for key, value in supplied.items() if key != "_chpm_gap_cursors"},
        "witnessed_utterances_not_world_facts": kept,
        **({"own_action_observations_not_world_facts": kept_actions} if actions else {}),
        **(
            {
                "private_notebook_not_world_facts": packed_context(
                    supplied["private_notebook_not_world_facts"], tier
                )
            }
            if "private_notebook_not_world_facts" in supplied
            else {}
        ),
        "appraisal_context": window.payload,
        "motivation_context": catalogue.payload(),
        "experience_context": narrative_context.experience_reasons(
            mind, continuation.experience_view(mind, supplied.get("_chpm_gap_cursors", {}))
        ),
        "context_packing": {
            "policy": "focused-view-budget-v2",
            "tier": tier,
            "dialogue_entries_omitted": len(previous) - len(kept),
            **({"action_entries_omitted": len(actions) - len(kept_actions)} if actions else {}),
            "canonical_history_changed": False,
        },
    }

    # Use a reference only when every character of the request is still present
    # in the current evidence. This removes duplication, never observations.
    observed = supplied.get("observation", {})
    current = [
        (alias, text)
        for alias, (_, source, text) in window.sources.items()
        if source.message_id == observed.get("message_id")
        and source.kind == "speech"
        and source.speaker_id == "@player"
    ]
    reference = {"player_request_source_ids": [alias for alias, _ in current]}
    literal = {"player_request": observed.get("player_request")}
    smaller = len(json.dumps(reference, ensure_ascii=False)) < len(
        json.dumps(literal, ensure_ascii=False)
    )
    if (
        current
        and smaller
        and "\n".join(text for _, text in current) == observed.get("player_request")
    ):
        result["observation"] = {
            key: value for key, value in observed.items() if key != "player_request"
        }
        result["observation"].update(reference)
    return result
