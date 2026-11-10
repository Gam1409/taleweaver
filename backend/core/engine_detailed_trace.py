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

from backend.core.diagnostic_fields import safe_error
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


def state_of(owner: Any) -> dict:
    owner = getattr(owner, "manager", owner)
    state = getattr(owner, "state", None)
    try:
        return {key: deepcopy(getattr(state, key)) for key in STATE_FIELDS if hasattr(state, key)}
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
            token = service.detail_token()
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
        service.detail(
            "detail.engine.failed",
            token=token,
            step=name,
            error=safe_error(exc),
            validation_reason=str(exc) if isinstance(exc, ValueError) else None,
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
    if service.detail_token() is None:
        return
    lines = chunk.splitlines()
    event = next((line[6:].strip() for line in lines if line.startswith("event:")), "message")
    text = "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
    try:
        data = json.loads(text)
    except ValueError:
        data = text
    service.detail("detail.engine.event", event_name=event, data=data)


@contextmanager
def turn_context(manager: Any, args: tuple, kwargs: dict) -> Iterator[None]:
    token = service.detail_token()
    if token is None:
        yield
        return
    started = time.perf_counter()
    turn_id = getattr(manager, "turn_id", None) or uuid4().hex
    with service.context(session_id=manager.game_id, turn_id=turn_id):
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
            token = service.detail_token()
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
                service.detail(
                    "detail.engine.failed",
                    token=token,
                    step=name,
                    error=safe_error(exc),
                    validation_reason=str(exc) if isinstance(exc, ValueError) else None,
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
