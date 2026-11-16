"""Explicit-only real-model suite. Ordinary pytest discovery never collects this file."""

import json
import os
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.inference import admission
from backend.core.inference.registry import Registry
from backend.models.chat import ChatMessage
from scripts.live_checks import artifacts
from scripts.live_checks.catalog import select as select_cases
from scripts.live_checks.checks import technical_checks, tool_coverage
from scripts.live_checks.scenarios import ACTIONS
from scripts.live_checks.signals import reported_affect
from scripts.live_checks.transport import Recorder
from tests.conftest import TestSessionLocal
from tests.live_support import FOREIGN_NOTE, prepare, provider_settings, snapshot

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("TALEWEAVER_LIVE_ENABLED") != "explicit-run",
        reason="Use scripts/run_live_checks.py run with an explicit endpoint and quota.",
    ),
]


def selections() -> list[tuple]:
    names = json.loads(os.environ.get("TALEWEAVER_LIVE_CASES", "[]"))
    repeats = int(os.environ.get("TALEWEAVER_LIVE_REPETITIONS", "1"))
    return [
        (case, repetition)
        for case in select_cases([], names)
        for repetition in range(1, repeats + 1)
    ]


@pytest.fixture(scope="session")
def live_run():
    plan = json.loads(os.environ["TALEWEAVER_LIVE_MANIFEST"])
    directory = artifacts.create(os.environ["TALEWEAVER_LIVE_RUN_ID"], plan)
    recorder = Recorder(
        os.environ["TALEWEAVER_LIVE_ENDPOINT"],
        int(os.environ["TALEWEAVER_LIVE_MAX_CALLS"]),
        directory,
    )
    registry = Registry(artifacts.target(directory, "inference-reservations.json"))
    return SimpleNamespace(directory=directory, recorder=recorder, registry=registry, settings=None)


async def run_turn(db, user, case, text: str, repetition: int, number: int, live_run) -> dict:
    recorder = live_run.recorder
    recorder.case_id, recorder.turn = f"{case.id}-{repetition}", number
    before = await snapshot(db)
    previous = set(await db.scalars(select(ChatMessage.id).where(ChatMessage.role == "assistant")))
    prior_prose = [
        message.content
        for message in await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ]
    calls_start, tools_start = len(recorder.calls), len(recorder.tool_calls)
    started = time.monotonic()
    manager = GameTurnManager(db, "session-1", user)
    events = [event async for event in manager.process_turn(text)]
    after = await snapshot(db)
    calls, tools = recorder.calls[calls_start:], recorder.tool_calls[tools_start:]
    messages = [
        message
        for message in await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        if message.id not in previous
    ]
    public = "\n".join(message.content for message in messages)
    errors = technical_checks(case, before, after, calls, tools, public, FOREIGN_NOTE)
    completed = any(event.startswith("event: final") for event in events)
    return {
        "case_id": case.id,
        "repetition": repetition,
        "turn": number,
        "group": case.group,
        "scenario": case.scenario,
        "mode": case.mode,
        "workflow": case.workflow,
        "protocol": case.protocol,
        "input": text,
        "prior_prose": prior_prose,
        "elapsed_s": time.monotonic() - started,
        "completed": completed,
        "errors": errors,
        "before": before,
        "after": after,
        "messages": [message.to_client_dict() for message in messages],
        "events": events,
        "calls": [row["number"] for row in calls],
        "tools": tools,
        "tool_coverage": tool_coverage(tools),
        "model_reported_affect": reported_affect(calls),
        "quality_review": "pending independent annotation",
    }


@pytest.mark.parametrize(
    "case,repetition", selections(), ids=lambda value: getattr(value, "id", str(value))
)
async def test_live_contract(case, repetition, live_run, monkeypatch):
    recorder = live_run.recorder
    if recorder.stopped:
        pytest.exit(
            "Earlier transport/quota stop; inspect saved results before retrying.", returncode=2
        )
    recorder.install(monkeypatch)
    monkeypatch.setattr(admission, "_registry", live_run.registry)
    tokens = int(os.environ["TALEWEAVER_LIVE_OUTPUT_TOKENS"])
    if live_run.settings is None:
        live_run.settings = await provider_settings(
            recorder.endpoint,
            os.environ.get("TALEWEAVER_LIVE_MODEL", ""),
            tokens,
            int(os.environ["TALEWEAVER_LIVE_TIMEOUT"]),
        )
    async with TestSessionLocal() as db:
        user, state = await prepare(db, case, live_run.settings, tokens)
        for number, text in enumerate(ACTIONS[case.scenario], 1):
            result = await run_turn(db, user, case, text, repetition, number, live_run)
            artifacts.append(live_run.directory, "results.jsonl", result)
            print(
                f"{case.id} turn {number}: completed={result['completed']}; calls={len(result['calls'])}",
                flush=True,
            )
            if recorder.stopped:
                pytest.exit(
                    "Transport/quota stop; inspect saved results before retrying.", returncode=2
                )
            assert result["completed"], "The turn did not produce an accepted final response."
            assert not result["errors"], "; ".join(result["errors"])
