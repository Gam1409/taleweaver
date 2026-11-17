"""Validate before the first visible chunk; at most one bounded prose repair."""

import asyncio
from typing import Any

from backend.core.engine_detailed_trace import step
from backend.core.llm_router import GameMasterLLM
from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.chpm import (
    agenda,
    continuation,
    continuation_writer,
    expression,
    inference,
    json_contract,
    narration_repair_input,
    passages,
    prompts,
)
from backend.engine.chpm.errors import (
    InferenceUnavailableError,
    RecoverableChpmError,
    StaleControlError,
)
from backend.engine.chpm.kernel import ChpmError, fingerprint
from backend.engine.chpm.runtime import Turn, contract_data, current
from backend.engine.chpm.schema import Verdict
from backend.engine.npc_actions import feedback as command_feedback
from backend.engine.npc_actions import instructions as command_instructions
from backend.engine.npc_presentation.runtime import clean_candidate, output_reminder


@step("narration.validate")
async def validate(
    manager: Any,
    text: str,
    *,
    completed: bool,
    resolution: str,
    system_prompt: str,
    narration_messages: list[dict[str, str]] | None = None,
    ordinary_context: str = "",
) -> str:
    text = clean_candidate(manager, text)
    turn = current(manager)
    if turn is not None and turn.simplified:
        if turn.simplified_text is None and turn.usage.fallback_reason == "review_rejected":
            raise ChpmError("No replacement for the rejected narration is available.")
        turn.simplified_text = turn.simplified_text or text
        return turn.simplified_text
    if turn is None or not turn.decisions or turn.initial.settings.mode != "live":
        return text
    if not completed or not text.strip():
        reject(
            "emotion",
            "chpm.narration_incomplete",
            "CHPM received an incomplete narration.",
            narration=text,
            completed=completed,
            decisions=turn.decisions,
            host_resolution=resolution,
        )
        if text.strip() and continuation.enabled(turn):
            continuation.activate(turn, "narration_incomplete")
            turn.simplified_text = text
            return text
        raise ChpmError("CHPM received an incomplete narration. No response was published.")
    try:
        return await _validated(
            manager, turn, text, resolution, system_prompt, narration_messages, ordinary_context
        )
    except RecoverableChpmError as exc:
        reject(
            "emotion",
            "chpm.review_unconfirmed",
            str(exc),
            narration=text,
            decisions=turn.decisions,
            host_resolution=resolution,
        )
        if turn.simplified or not continuation.enabled(turn):
            raise
        continuation.activate(turn, "review_unavailable", error=exc)
        turn.simplified_text = text
        return text


async def _validated(
    manager: Any,
    turn: Turn,
    text: str,
    resolution: str,
    system_prompt: str,
    narration_messages: list[dict[str, str]] | None,
    ordinary_context: str,
) -> str:
    original_text = text
    verdict = await _review(manager, turn, text, resolution)
    if not verdict.matches:
        try:
            if turn.usage.calls + 2 > turn.initial.settings.max_calls_per_turn:
                raise RecoverableChpmError(
                    "CHPM needs two remaining requests for repair and review."
                )
            text = await _repair(manager, turn, text, resolution, verdict.issues, system_prompt)
        except RecoverableChpmError:
            return await _rejected(
                manager,
                turn,
                resolution,
                system_prompt,
                verdict.issues,
                narration_messages,
                ordinary_context,
                rejected_texts=(original_text,),
            )
        except Exception as exc:
            raise ChpmError(
                f"CHPM repair failed ({type(exc).__name__}). No response was published."
            ) from exc
        # A repair can echo the rejected candidate. Only a different reply may
        # continue as explicitly unreviewed when its reviewer is unavailable.
        try:
            verdict = await _review(manager, turn, text, resolution)
        except RecoverableChpmError as exc:
            if not continuation.enabled(turn):
                raise
            if _candidate_key(text) == _candidate_key(original_text):
                return await _rejected(
                    manager,
                    turn,
                    resolution,
                    system_prompt,
                    verdict.issues,
                    narration_messages,
                    ordinary_context,
                    rejected_texts=(original_text,),
                )
            continuation.activate(turn, "review_unavailable", error=exc)
            turn.simplified_text = text
            return text
    if not verdict.matches:
        return await _rejected(
            manager,
            turn,
            resolution,
            system_prompt,
            verdict.issues,
            narration_messages,
            ordinary_context,
            rejected_texts=(original_text, text),
        )
    turn.verdict = verdict
    turn.usage.status = "validated"
    return text


async def _rejected(
    manager: Any,
    turn: Turn,
    resolution: str,
    system_prompt: str,
    issues: list[str],
    narration_messages: list[dict[str, str]] | None,
    ordinary_context: str,
    *,
    rejected_texts: tuple[str, ...],
) -> str:
    reject(
        "emotion",
        "chpm.narration_discarded",
        "; ".join(issues),
        narrations=rejected_texts,
        decisions=turn.decisions,
        host_resolution=resolution,
        issues=issues,
        confirmed_state=turn.initial,
    )
    if not continuation.enabled(turn):
        raise ChpmError("CHPM dialogue validation failed after one repair: " + "; ".join(issues))
    continuation.activate(turn, "review_rejected", issues)
    replacement = await continuation_writer.generate(
        manager, turn, resolution, system_prompt, narration_messages, ordinary_context
    )
    if _candidate_key(replacement) in {_candidate_key(text) for text in rejected_texts}:
        raise ChpmError("The ordinary narrator repeated an already rejected candidate.")
    turn.simplified_text = replacement
    return turn.simplified_text


def _candidate_key(text: str) -> str:
    return " ".join(text.split())


@step("narration.review")
async def _review(manager: Any, turn: Turn, text: str, resolution: str) -> Verdict:
    from backend.engine.chpm import reports

    available = passages.index(text)
    control, observed = _review_control(manager, turn)
    instruction = (
        prompts.VERIFY
        + command_instructions.resolution_instructions(turn.action_outcomes)
        + command_feedback.instructions(turn)
    )
    payload = _review_payload(turn, available, resolution)
    identifiers = _review_identifiers(turn, available, scope=payload["review_scope"])
    if turn.report_origins and not inference.fits(
        turn.initial.settings, instruction, payload, passages.SharedReview, identifiers
    ):
        reports.disable(turn)
        payload = _review_payload(turn, available, resolution)
        identifiers = _review_identifiers(turn, available, scope=payload["review_scope"])
    raw: passages.SharedReview | passages.Review | Verdict = await inference.request(
        manager,
        turn.initial.settings,
        turn.usage,
        instruction,
        payload,
        passages.SharedReview,
        "validation",
        identifiers=identifiers,
    )
    _validate_review_scope(raw, turn, available, text, resolution, payload)
    _ensure_review_current(manager, control, observed)
    if not raw.matches:
        _reject_review(turn, text, resolution, raw.issues, raw, payload)
        return Verdict(
            matches=False,
            issues=raw.issues or ["The dialogue validator rejected this candidate."],
        )
    try:
        verdict = _resolve_review(raw, turn, available, text)
    except ChpmError as exc:
        _reject_review(turn, text, resolution, [str(exc)], raw, payload)
        raise RecoverableChpmError(str(exc)) from exc
    try:
        expression.validate(turn.decisions, verdict, text)
    except ChpmError as exc:
        _reject_review(turn, text, resolution, [str(exc)], verdict, payload)
        raise RecoverableChpmError(str(exc)) from exc
    if verdict.matches and verdict.issues:
        _reject_review(
            turn, text, resolution, ["Contradictory validation verdict."], verdict, payload
        )
        raise RecoverableChpmError("CHPM validator returned a contradictory verdict.")
    issues = _deferred_speech(turn, verdict, text)
    if issues:
        _reject_review(turn, text, resolution, issues, verdict, payload)
        return Verdict(matches=False, issues=issues)
    try:
        _validate_hearing(turn, verdict, text)
    except ChpmError as exc:
        _reject_review(turn, text, resolution, [str(exc)], verdict, payload)
        raise
    try:
        agenda.validate_evidence(turn.decisions, verdict)
    except ChpmError as exc:
        _reject_review(turn, text, resolution, [str(exc)], verdict, payload)
        return Verdict(matches=False, issues=[str(exc)])
    return verdict


def _resolve_review(
    raw: passages.SharedReview | passages.Review | Verdict,
    turn: Turn,
    available: dict[str, str],
    text: str,
) -> Verdict:
    if isinstance(raw, passages.SharedReview):
        return passages.resolve_shared(
            raw,
            available,
            agenda_actors={
                actor
                for actor, decision in turn.decisions.items()
                if decision.selected.agenda_change
            },
            text=text,
        )
    if isinstance(raw, passages.Review):
        return passages.resolve(raw, available, text=text)
    return raw


def _review_control(manager: Any, turn: Turn) -> tuple[dict, Any]:
    observed = next(iter(turn.decisions.values())).observation
    control = turn_controls.scope(manager, "narration_review", observation=observed)
    if not getattr(turn, "control", None):
        turn.control = control
    _ensure_review_current(manager, turn.control, observed)
    turn.review_operation = turn_controls.operation(control, "narration_review").model_dump(
        exclude_none=True
    )
    return control, observed


def _ensure_review_current(manager: Any, control: dict, observed: Any) -> None:
    if not turn_controls.bind_current(manager, control, "narration_review", observation=observed):
        raise StaleControlError("CHPM narration review belongs to an inactive turn attempt.")


def _validate_review_scope(
    raw: passages.SharedReview | passages.Review | Verdict,
    turn: Turn,
    available: dict,
    text: str,
    resolution: str,
    payload: dict,
) -> None:
    if not isinstance(raw, passages.SharedReview):
        return
    try:
        json_contract.validate_identifiers(
            type(raw),
            raw.model_dump(mode="json"),
            _review_identifiers(turn, available, scope=payload["review_scope"]),
        )
        passages.validate_shared(raw, payload["review_scope"], available, set(turn.decisions))
    except ValueError as exc:
        _reject_review(turn, text, resolution, [str(exc)], raw, payload)
        raise RecoverableChpmError(str(exc)) from exc


def _deferred_speech(turn: Turn, verdict: Verdict, text: str) -> list[str]:
    speakers = {
        entry.speaker_id
        for entry in verdict.heard
        if entry.actor_id in turn.decisions
        and entry.speaker_id in turn.deferred_names
        and entry.speaker_id in turn.present_names
        and entry.speaker_id != entry.actor_id
        and entry.quote
        and entry.quote in text
    }
    return [
        f"Inactive controlled NPC {speaker} has new spoken dialogue; "
        "retain only its established unchanged presence."
        for speaker in sorted(speakers)
    ][:8]


def _reject_review(
    turn: Turn, text: str, resolution: str, issues: list[str], verdict: Any, context: dict
) -> None:
    reject(
        "emotion",
        "chpm.narration_rejected",
        "; ".join(issues) or "The validator rejected this candidate.",
        narration=text,
        host_resolution=resolution,
        verdict=verdict,
        decisions=turn.decisions,
        context=context,
    )


def _review_payload(turn: Turn, available: dict[str, str], resolution: str) -> dict:
    from backend.engine.chpm import reports

    return {
        "contract": contract_data(turn),
        "player_request": turn.player_request,
        "host_resolution": resolution,
        **command_instructions.resolution_timing(turn.action_outcomes),
        "present_speakers": turn.present_names,
        "controlled_actor_ids": sorted(turn.decisions),
        "inactive_controlled_actors": turn.deferred_names,
        "passages": available,
        "request_control": _review_request_control(turn),
        "review_scope": _review_scope(turn, available, resolution),
        "report_origins_not_world_facts": reports.context(turn),
        **(
            {"host_rejections_before_commands": turn.host_rejections}
            if getattr(turn, "host_rejections", None)
            else {}
        ),
    }


def _review_request_control(turn: Turn) -> dict:
    if not turn.review_operation:
        turn.review_operation = turn_controls.operation(
            turn_controls.scope(turn, "narration_review"), "narration_review"
        ).model_dump(exclude_none=True)
    return turn_controls.request_view(turn_controls.Operation.model_validate(turn.review_operation))


def _review_scope(turn: Turn, available: dict, resolution: str) -> str:
    _review_request_control(turn)
    return fingerprint(
        {
            "input": turn.input_id,
            "revision": turn.initial.revision,
            "observations": {
                actor: decision.observation.model_dump(exclude={"player_request"})
                for actor, decision in turn.decisions.items()
            },
            "passages": available,
            "resolution": resolution,
            "control": turn_controls.scope(turn, "narration_review"),
            "host_rejections": getattr(turn, "host_rejections", []),
            "contract": contract_data(turn),
            "action_outcomes": turn.action_outcomes,
            "operation": turn.review_operation,
        }
    )


def preflight(turn: Turn) -> None:
    """Reserve prose/resolution headroom before paying for the narrator call."""
    if turn.initial.settings.mode != "live" or not turn.decisions:
        return
    from backend.engine.chpm import reports

    remaining = _review_room(turn)
    if remaining < 3072 and turn.report_origins:
        reports.disable(turn)
        remaining = _review_room(turn)
    # Leave space for resolution, passage keys and escaped text. The final
    # request is still checked exactly; unforeseen huge resolutions fail visibly.
    turn.reply_character_budget = min(4096, (remaining - 2048) // 2)
    if turn.reply_character_budget < 512:
        raise RecoverableChpmError(
            "CHPM review contract leaves insufficient reply space; increase input budget before narration."
        )


def _review_room(turn: Turn) -> int:
    payload = _review_payload(turn, {}, "")
    prompt, content = inference.compose(
        prompts.VERIFY
        + command_instructions.resolution_instructions(turn.action_outcomes)
        + command_feedback.instructions(turn),
        payload,
        passages.SharedReview,
        _review_identifiers(turn, {}, scope=payload["review_scope"]),
    )
    return turn.initial.settings.max_input_chars - len(prompt) - len(content)


def _review_identifiers(turn: Turn, available: dict, *, scope: str | None = None) -> dict:
    return {
        "actor_id": sorted(turn.decisions),
        "speaker_id": sorted(turn.present_names),
        "passage_id": list(available),
        "origin_id": sorted(turn.report_origins),
        "review_scope": [scope or _review_scope(turn, available, "")],
    }


def _validate_hearing(turn: Turn, verdict: Verdict, text: str) -> None:
    from backend.engine.chpm import reports

    for entry in verdict.heard:
        if (
            entry.actor_id not in turn.decisions
            or entry.speaker_id not in turn.present_names
            or entry.speaker_id == entry.actor_id
            or entry.speaker_id in turn.deferred_names
            or not entry.quote
            or entry.quote not in text
        ):
            raise RecoverableChpmError(
                "CHPM hearing evidence has an invalid observer, speaker, or quote."
            )
        try:
            reports.origin_for(turn, entry.speaker_id, entry.origin_id)
        except ValueError as exc:
            raise RecoverableChpmError(str(exc)) from exc


@step("narration.repair")
async def _repair(
    manager: Any, turn: Turn, text: str, resolution: str, issues: list[str], system_prompt: str
) -> str:
    system, payload = narration_repair_input.build(
        turn,
        system_prompt + command_feedback.instructions(turn),
        text,
        resolution,
        issues,
        portrait_reminder=output_reminder(manager),
    )
    inference.reserve(turn.initial.settings, turn.usage, len(system) + len(payload))
    turn.usage.repairs += 1
    # Repair rewrites the full narrator response, including unaffected NPC voices.
    # Keep the narrator's Complex role even when cognitive proposals use Small.
    llm = inference.model_for(manager, "complex", GameMasterLLM)
    llm.enable_thinking = False
    llm.max_tokens = min(llm.max_tokens, 4096)
    try:
        result = await asyncio.wait_for(
            llm.aexecute_simple_task(
                system,
                payload,
                llm.model,
                game_id=manager.game_id,
                operation="chpm",
                phase="repair",
            ),
            timeout=float(llm.request_timeout),
        )
    except Exception as exc:
        raise InferenceUnavailableError(f"CHPM repair failed ({type(exc).__name__}).") from exc
    if not isinstance(result, str):
        raise RecoverableChpmError("CHPM repair returned a non-text response.")
    turn.usage.output_chars += len(result)
    return clean_candidate(manager, result)
