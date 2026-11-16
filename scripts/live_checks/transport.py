"""Transparent observation of the real admitted gateway, including streamed/native calls."""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import artifacts

REQUEST_FIELDS = (
    "model",
    "messages",
    "tools",
    "tool_choice",
    "response_format",
    "max_tokens",
    "stream",
)


class RunStoppedError(RuntimeError):
    """No more requests may be dispatched in this run."""


def serializable(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


@dataclass
class Recorder:
    endpoint: str
    maximum: int
    directory: Path | None = None
    calls: list[dict] = field(default_factory=list)
    stopped: bool = False
    case_id: str = ""
    turn: int = 0
    tool_calls: list[dict] = field(default_factory=list)

    def reserve(self, router: Any, kwargs: dict) -> dict:
        if self.stopped or len(self.calls) >= self.maximum:
            self.stopped = True
            raise RunStoppedError("Run stopped: gateway quota or an earlier uncertain request.")
        if router.provider != "custom_openai" or router.api_base != self.endpoint:
            self.stopped = True
            raise RunStoppedError("Run stopped: a role attempted another provider or endpoint.")
        row = {
            "number": len(self.calls) + 1,
            "case_id": self.case_id,
            "turn": self.turn,
            "request": {key: serializable(kwargs[key]) for key in REQUEST_FIELDS if key in kwargs},
            "elapsed_s": None,
            "first_chunk_s": None,
            "usage": None,
            "status": "pending",
            "response": None,
        }
        self.calls.append(row)
        return row

    def finish(self, row: dict, started: float, status: str, response: Any = None) -> None:
        row.update(elapsed_s=round(time.monotonic() - started, 6), status=status)
        if response is not None:
            payload = serializable(response)
            row["response"] = payload
            row["usage"] = payload.get("usage") if isinstance(payload, dict) else None
        self.stopped = self.stopped or status not in {"complete", "rejected"}
        if self.directory is not None:
            try:
                artifacts.append(self.directory, "calls.jsonl", row)
            except (OSError, ValueError):
                self.stopped = True
                raise

    def install(self, monkeypatch: Any) -> None:
        from backend.core.llm_router import GameMasterLLM

        original = GameMasterLLM._acompletion_with_openrouter_fallback
        recorder = self

        async def observed(router: Any, kwargs: dict) -> Any:
            row = recorder.reserve(router, kwargs)
            started = time.monotonic()
            try:
                response = await original(router, kwargs)
            except BaseException as exc:
                from backend.core.inference.admission import rejected

                recorder.finish(
                    row, started, "rejected" if rejected(exc) else "uncertain_transport"
                )
                raise
            if kwargs.get("stream"):
                return recorder.stream(response, row, started)
            recorder.finish(row, started, "complete", response)
            return response

        monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", observed)
        self.observe_tools(monkeypatch)

    def observe_tools(self, monkeypatch: Any) -> None:
        from backend.engine.chpm.agent_tools import Tools

        original = Tools.execute
        recorder = self

        def execute(tools: Any, request: Any) -> dict:
            result = original(tools, request)
            recorder.tool_calls.append(
                {
                    "case_id": recorder.case_id,
                    "turn": recorder.turn,
                    "actor_id": tools.mind.genesis.scope.observer_id,
                    "request": request.model_dump(mode="json"),
                    "result": result,
                }
            )
            return result

        monkeypatch.setattr(Tools, "execute", execute)

    async def stream(self, response: Any, row: dict, started: float) -> Any:
        chunks, complete = [], False
        try:
            async for chunk in response:
                if row["first_chunk_s"] is None:
                    row["first_chunk_s"] = round(time.monotonic() - started, 6)
                chunks.append(serializable(chunk))
                yield chunk
            complete = True
        finally:
            usages = [
                chunk.get("usage")
                for chunk in chunks
                if isinstance(chunk, dict) and chunk.get("usage")
            ]
            try:
                await self.close_stream(response)
            except BaseException:
                complete = False
                raise
            finally:
                self.finish(
                    row,
                    started,
                    "complete" if complete else "incomplete_stream",
                    {"chunks": chunks, "usage": usages[-1] if usages else None},
                )

    async def close_stream(self, response: Any) -> None:
        close = getattr(response, "aclose", None)
        if close is not None:
            await asyncio.shield(close())
