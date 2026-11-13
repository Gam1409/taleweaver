"""Opt-in engine boundary traces; observe state without changing gameplay or its text."""

import json
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from inspect import signature
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.orm.state import InstanceState

from backend.core.diagnostic_failures import failure_details
from backend.core.state_rejection_trace import reject, scope
from backend.core.system_diagnostics import service

P = ParamSpec("P")
T = TypeVar("T")
STATE_FIELDS = (
    "current_scene_id",
    "in_game_time",
    "inventory",
    "entity_states",
    "exit_states",
    "living_world",
    "is_completed",
    "discovered_scenes",
    "quests",
    "world_memories",
    "world_rumors",
    "active_sequence_id",
    "active_sequence_order",
    "plot",
    "rules",
    "completed_condition",
    "gameover_condition",
    "completed_guard_expression",
    "gameover_guard_expression",
    "allow_dynamic_items",
)
AVATAR_FIELDS = (
    "id",
    "hp",
    "max_hp",
    "stamina",
    "max_stamina",
    "mana",
    "max_mana",
    "exp",
    "stats",
    "inventory",
    "equipment",
    "status_effects",
)
ARGUMENTS = {
    "text",
    "message",
    "user_msg",
    "resolution",
    "completed",
    "payload",
    "proposal",
    "proposals",
    "event",
    "entry",
    "role",
    "content",
    "actor_id",
    "message_id",
}


def _loaded(owner: Any, name: str, default: Any = None) -> Any:
    inspected = inspect(owner, raiseerr=False)
    if isinstance(inspected, InstanceState):
        return inspected.dict.get(name, default)
    return getattr(owner, name, default)


def _snapshot(owner: Any, fields: tuple[str, ...]) -> dict:
    missing = object()
    result = {}
    for key in fields:
        part = _loaded(owner, key, missing)
        if part is not missing:
            result[key] = deepcopy(part)
    return result


def state_of(owner: Any) -> dict:
    try:
        owner = _loaded(owner, "manager", owner)
        result = _snapshot(_loaded(owner, "state"), STATE_FIELDS)
        avatar = _loaded(owner, "avatar")
        if avatar is not None:
            result["avatar"] = _snapshot(avatar, AVATAR_FIELDS)
        return result
    except Exception as exc:
        return {"capture_error": type(exc).__name__}


def changes(before: dict, after: dict) -> dict:
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    }


def step(
    name: str, *, result: bool = True
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    def decorate(method: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        parameters = signature(method)

        @wraps(method)
        async def observed(*args: P.args, **kwargs: P.kwargs) -> T:
            token = service.capture_token()
            if token is None:
                return await method(*args, **kwargs)
            supplied = parameters.bind(*args, **kwargs).arguments
            owner = args[0] if args else None
            before = state_of(owner)
            started = time.perf_counter()
            parent = service.current_context().get("step_id")
            with service.context(step_id=uuid4().hex, parent_step_id=parent):
                service.detail(
                    "detail.engine.started",
                    token=token,
                    step=name,
                    function=f"{method.__module__}.{method.__qualname__}",
                    arguments={key: part for key, part in supplied.items() if key in ARGUMENTS},
                )
                return await _run(method, args, kwargs, name, token, started, owner, before, result)

        return observed

    return decorate


async def _run(
    method: Callable[..., Awaitable[T]],
    args: tuple,
    kwargs: dict,
    name: str,
    token: int,
    started: float,
    owner: Any,
    before: dict,
    include_result: bool,
) -> T:
    try:
        result = await method(*args, **kwargs)
    except BaseException as exc:
        failure = failure_details(exc)
        service.detail(
            "detail.engine.failed",
            token=token,
            step=name,
            error=failure["error"],
            validation_reason=failure.get("failure_reason")
            if isinstance(exc, ValueError)
            else None,
            state_changes=changes(before, state_of(owner)),
        )
        raise
    service.detail(
        "detail.engine.completed",
        token=token,
        step=name,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        result=result if include_result else None,
        state_changes=changes(before, state_of(owner)),
    )
    return result


def stream_event(chunk: str) -> None:
    if service.capture_token() is None:
        return
    lines = chunk.splitlines()
    event = next((line[6:].strip() for line in lines if line.startswith("event:")), "message")
    text = "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
    try:
        data = json.loads(text)
    except ValueError:
        data = text
    service.detail("detail.engine.event", event_name=event, data=data)
    if event == "error":
        reject(
            "turn",
            "engine_error_event",
            "The turn emitted an explicit error event.",
            event_payload=data,
        )
    if event == "final" and isinstance(data, dict) and data.get("narration_incomplete") is True:
        reject(
            "turn",
            "narration_incomplete",
            "The final narration was explicitly marked incomplete.",
            event_payload=data,
        )


@contextmanager
def turn_context(manager: Any, args: tuple, kwargs: dict) -> Iterator[None]:
    token = service.capture_token()
    if token is None:
        yield
        return
    started = time.perf_counter()
    turn_id = getattr(manager, "turn_id", None) or uuid4().hex
    with (
        service.context(session_id=manager.game_id, turn_id=turn_id),
        scope(session_id=manager.game_id, turn_id=turn_id, operation="turn"),
    ):
        service.detail(
            "detail.engine.turn.started",
            token=token,
            player_input=args[0] if args else kwargs.get("user_msg"),
            replay_message_id=kwargs.get("replay_message_id"),
        )
        try:
            yield
        finally:
            service.detail(
                "detail.engine.turn.ended",
                token=token,
                state=state_of(manager),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )


def sync_step(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(method: Callable[P, T]) -> Callable[P, T]:
        parameters = signature(method)

        @wraps(method)
        def observed(*args: P.args, **kwargs: P.kwargs) -> T:
            token = service.capture_token()
            if token is None:
                return method(*args, **kwargs)
            supplied = parameters.bind(*args, **kwargs).arguments
            owner = args[0] if args else None
            before = state_of(owner)
            service.detail(
                "detail.engine.started",
                token=token,
                step=name,
                arguments={key: part for key, part in supplied.items() if key in ARGUMENTS},
            )
            try:
                result = method(*args, **kwargs)
            except BaseException as exc:
                failure = failure_details(exc)
                service.detail(
                    "detail.engine.failed",
                    token=token,
                    step=name,
                    error=failure["error"],
                    validation_reason=failure.get("failure_reason")
                    if isinstance(exc, ValueError)
                    else None,
                )
                raise
            service.detail(
                "detail.engine.completed",
                token=token,
                step=name,
                result=result,
                state_changes=changes(before, state_of(owner)),
            )
            return result

        return observed

    return decorate
