"""Optional bounded lookup loop before the existing validated decision boundary."""

from typing import Any

from backend.engine.chpm import host_observations, inference
from backend.engine.chpm.agent_contracts import INSTRUCTIONS, Step
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Observation, Settings, Usage


async def investigate(
    manager: Any,
    settings: Settings,
    usage: Usage,
    mind: Mind,
    observation: Observation,
    supplied: dict,
) -> tuple[Tools, list[dict]]:
    if (
        mind.genesis.scope.world_id != observation.session_id
        or manager.game_id != observation.session_id
    ):
        raise ChpmError("CHPM agent observation belongs to another session.")
    turn = getattr(manager, "_chpm_turn", None)
    clothing = (
        getattr(turn, "agent_clothing", {})
        if getattr(turn, "input_id", None) == observation.message_id
        else {}
    )
    tools = Tools(mind, observation, clothing)
    facts = host_observations.previous(mind)
    transcript: list[dict] = []
    audit: list[dict] = []
    for index in range(settings.agent_steps):
        try:
            step = await inference.request(
                manager,
                settings.model_copy(
                    update={"max_output_tokens": min(768, settings.max_output_tokens)}
                ),
                usage,
                INSTRUCTIONS,
                {
                    "observer_id": mind.genesis.scope.observer_id,
                    "identity": mind.genesis.identity.model_dump(mode="json"),
                    "observation": observation.model_dump(),
                    "current_state": supplied.get("psychological_state", {}),
                    "agenda": supplied.get("declared_agenda_not_world_facts", []),
                    "visible_clothing_actors": {
                        key: value["name"]
                        for key, value in tools.clothing.items()
                        if facts and key in facts.visible_actor_ids
                    },
                    "remaining_rounds": settings.agent_steps - index,
                    "previous_lookups": transcript,
                },
                Step,
                "agent_lookup",
            )
        except (inference.InvalidResponseError, inference.OutputBudgetError) as exc:
            # A completed but malformed optional plan is not evidence of no memory.
            # Never execute a partially valid batch or retry an uncertain transport.
            audit.append(
                {
                    "purpose": "",
                    "requests": [],
                    "results": [],
                    "stop": "invalid_plan",
                    "error_type": type(exc).__name__,
                    "lookup_performed": False,
                }
            )
            break
        results = [tools.execute(request) for request in step.requests]
        transcript.append({"requests": [r.model_dump() for r in step.requests], "results": results})
        audit.append(
            {
                "purpose": step.purpose[:180],
                "purpose_truncated": len(step.purpose) > 180,
                "requests": [r.model_dump() for r in step.requests],
                "results": [_summary(result) for result in results],
                "stop": "ready"
                if not step.requests
                else "step_limit"
                if index + 1 == settings.agent_steps
                else "continue",
            }
        )
        if not step.requests:
            break
    return tools, audit


def _summary(result: dict) -> dict:
    return {
        key: [_summary(item) for item in value] if key == "results" else value
        for key, value in result.items()
        if key not in {"text"}
    }
