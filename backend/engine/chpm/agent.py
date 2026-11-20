"""Optional bounded lookup loop before the existing validated decision boundary."""

from typing import Any

from backend.engine.chpm import (
    agent_lookup_payload,
    agent_native,
    inference,
    tool_operations,
)
from backend.engine.chpm.agent_contracts import (
    INSTRUCTIONS,
    NOTEBOOK_INSTRUCTIONS,
    NotebookStep,
    Step,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind, Source
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.notebook_tools import NotebookDraft, request_summary, result_summary
from backend.engine.chpm.schema import Observation, Settings, Usage


async def investigate(
    manager: Any,
    settings: Settings,
    usage: Usage,
    mind: Mind,
    observation: Observation,
    supplied: dict,
    *,
    pinned: dict[str, tuple[str, Source, str]] | None = None,
    notebook: NotebookDraft | None = None,
) -> tuple[Tools, list[dict]]:
    tools = make_tools(manager, mind, observation, pinned=pinned, notebook=notebook)
    if settings.agent_steps and (notebook is not None or settings.tool_profile != "auto"):
        native_model = agent_native.select_model(manager, settings)
        if native_model is not None:
            return await agent_native.investigate(
                manager,
                settings,
                usage,
                mind,
                observation,
                supplied,
                tools=tools,
                notebook=notebook,
                llm=native_model,
            )
    transcript: list[dict] = []
    captured = tool_operations.capture(manager, tools)
    audit: list[dict] = []
    contract: type[Step] | type[NotebookStep] = NotebookStep if notebook else Step
    for index in range(settings.agent_steps):
        try:
            step: Step | NotebookStep = await inference.request(
                manager,
                settings.model_copy(
                    update={"max_output_tokens": min(768, settings.max_output_tokens)}
                ),
                usage,
                NOTEBOOK_INSTRUCTIONS if notebook else INSTRUCTIONS,
                agent_lookup_payload.build(
                    mind, observation, supplied, tools, settings.agent_steps - index, transcript
                ),
                contract,
                "agent_lookup",
            )
        except (inference.InvalidResponseError, inference.OutputBudgetError) as exc:
            # A completed but malformed optional plan is not evidence of no memory.
            # Never execute a partially valid batch or retry an uncertain transport.
            if notebook:
                notebook.committable = False
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
        calls = tool_operations.legacy_calls(step.requests)
        batch = tool_operations.execute(manager, tools, calls, step.requests, captured=captured)
        results = [
            tool_operations.for_model(call.name, result)
            for call, result in tool_operations.feedback(batch)
        ]
        issued = tuple(batch.operations.values())
        request_ids = [
            {"attempt_id": operation.attempt_id, "operation_id": operation.operation_id}
            for operation in issued
        ]
        transcript.append(
            {
                "requests": [
                    {**request.model_dump(), **identifiers}
                    for request, identifiers in zip(step.requests, request_ids, strict=True)
                ],
                "results": results,
            }
        )
        audit.append(
            {
                # A model may quote private notes in its free-form purpose too.
                "purpose": "Private memory tool round" if notebook else step.purpose[:180],
                "purpose_truncated": False if notebook else len(step.purpose) > 180,
                "requests": [
                    {
                        **(request_summary(request) if notebook else request.model_dump()),
                        **identifiers,
                    }
                    for request, identifiers in zip(step.requests, request_ids, strict=True)
                ],
                "results": [
                    result_summary(result) if notebook else _summary(result)
                    for result in batch.results
                ],
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


def make_tools(
    manager: Any,
    mind: Mind,
    observation: Observation,
    *,
    pinned: dict[str, tuple[str, Source, str]] | None = None,
    notebook: NotebookDraft | None = None,
) -> Tools:
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
    hits = getattr(turn, "semantic_hits", {}).get(mind.genesis.scope.observer_id, [])
    return Tools(
        mind,
        observation,
        clothing,
        pins=dict(pinned or {}),
        semantic_scores={hit.record_id: hit.score for hit in hits},
        episode_contexts={hit.record_id: hit.context for hit in hits},
        notebook=notebook,
        observable=getattr(turn, "observable_views", {}).get(mind.genesis.scope.observer_id)
        if getattr(turn, "input_id", None) == observation.message_id
        else None,
        actions=getattr(turn, "action_drafts", {}).get(mind.genesis.scope.observer_id)
        if getattr(turn, "input_id", None) == observation.message_id
        else None,
    )
