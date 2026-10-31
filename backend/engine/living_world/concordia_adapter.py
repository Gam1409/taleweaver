"""Optional Concordia 2.4 sequential engine, with all inference on our async router."""

import asyncio
import concurrent.futures
import json
import sys
import threading
from collections.abc import Callable, Coroutine
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from backend.engine.living_world.decisions import Decision


def available() -> bool:
    try:
        return sys.version_info >= (3, 12) and version("gdm-concordia") == "2.4.0"
    except PackageNotFoundError:
        return False


class Bridge:
    """One remote action maximum; cancellation cannot start another request."""

    def __init__(self, callback: Callable[[], Coroutine[Any, Any, Decision]]) -> None:
        self.loop = asyncio.get_running_loop()
        self.callback = callback
        self.lock = threading.Lock()
        self.closed = False
        self.future: concurrent.futures.Future[Decision] | None = None

    def act(self) -> Decision:
        with self.lock:
            if self.closed or self.future is not None:
                raise RuntimeError("Concordia exceeded the single-action boundary.")
            self.future = asyncio.run_coroutine_threadsafe(self.callback(), self.loop)
            future = self.future
        return future.result()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.future is not None:
                self.future.cancel()


class Actor:
    def __init__(self, name: str, bridge: Bridge) -> None:
        self.name = name
        self.bridge = bridge
        self.observation = ""
        self.result: Decision | None = None

    def observe(self, observation: str) -> None:
        self.observation = observation

    def act(self, action_spec: Any) -> str:
        if not self.observation:
            raise ValueError("Concordia actor received no grounded observation.")
        self.result = self.bridge.act()
        result = self.result.model_dump_json()
        action_spec.validate(result)
        return result


class GameMaster:
    """Concordia orchestration is deterministic; SQL remains the final authority."""

    name = "TaleWeaver"

    def __init__(self, context: dict[str, Any], actor: Actor) -> None:
        self.context = context
        self.actor = actor
        self.resolved = False

    def observe(self, observation: str) -> None:
        # Putative text never updates SQL or becomes an observation on its own.
        if not isinstance(observation, str):
            raise ValueError("Invalid Concordia observation.")

    def act(self, action_spec: Any) -> str:
        kind = action_spec.output_type.value
        if kind == "terminate":
            return "Yes" if self.resolved else "No"
        if kind == "make_observation":
            return json.dumps(self.context, ensure_ascii=False)
        if kind == "next_acting":
            return self.actor.name
        if kind == "next_action_spec":
            return json.dumps(
                {"call_to_action": "Choose a grounded JSON action.", "output_type": "free"}
            )
        if kind != "resolve" or self.actor.result is None:
            raise ValueError("Unsupported Concordia game-master action.")
        decision = self.actor.result
        if decision.action == "MOVE" and decision.destination not in self.context["destinations"]:
            raise ValueError("Concordia action selected an unavailable destination.")
        self.resolved = True
        return decision.model_dump_json()


def _run(context: dict[str, Any], bridge: Bridge) -> Decision:
    sequential = import_module("concordia.environment.engines.sequential").Sequential

    actor = Actor(context["actor"]["id"], bridge)
    master = GameMaster(context, actor)
    sequential().run_loop(game_masters=[master], entities=[actor], max_steps=1, verbose=False)
    if not master.resolved or actor.result is None:
        raise ValueError("Concordia completed without a resolved proposal.")
    return actor.result


async def decide(
    context: dict[str, Any], callback: Callable[[], Coroutine[Any, Any, Decision]]
) -> Decision:
    if not available():
        raise ValueError(
            "Install the concordia extra on Python 3.12 or 3.13 (gdm-concordia 2.4.0)."
        )
    bridge = Bridge(callback)
    try:
        return await asyncio.to_thread(_run, context, bridge)
    finally:
        bridge.close()
