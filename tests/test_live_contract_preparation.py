"""Offline tests of isolation, transport transparency, quotas and independent review."""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.live_checks import artifacts, cli, review
from scripts.live_checks.catalog import CASES, manifest
from scripts.live_checks.scenarios import ACTIONS
from scripts.live_checks.signals import reported_affect
from scripts.live_checks.transport import Recorder, RunStoppedError
from tests.conftest import TestSessionLocal
from tests.live_support import prepare, snapshot


def test_catalog_has_consistent_turns_and_independent_off_on_emotion_pairs():
    assert len(CASES) == len({case.id for case in CASES}) == 25
    assert all(case.turns == len(ACTIONS[case.scenario]) for case in CASES)
    for situation in ("overt", "concealed", "mixed", "repair"):
        pair = [case for case in CASES if case.group == "emotions" and case.scenario == situation]
        assert {case.mode for case in pair} == {"off", "live"}
        assert {case.workflow for case in pair} == {"integrated"}
    assert manifest(list(CASES), 3)["planned_executions"] == 75


@pytest.mark.parametrize(
    "base",
    [
        "https://model.example",
        "https://model.example/v1/",
        "https://model.example/v1/chat/completions",
    ],
)
def test_endpoint_normalization(base):
    assert cli.endpoint(base) == "https://model.example/v1"


@pytest.mark.parametrize("protocol", ["plain", "json", "native"])
def test_declared_affect_comes_from_decision_not_prose_or_notebook(protocol):
    proposal = {
        "candidates": {},
        "experiences": [{"channel": "affect", "dimension": "fear", "level": "moderate"}],
    }
    message = {"content": json.dumps(proposal)}
    if protocol == "json":
        message = {
            "content": json.dumps(
                {"requests": [{"name": "submit_decision", "arguments": proposal}]}
            )
        }
    if protocol == "native":
        message = {
            "tool_calls": [
                {"function": {"name": "submit_decision", "arguments": json.dumps(proposal)}}
            ]
        }
    assert reported_affect([{"response": {"choices": [{"message": message}]}}]) == ["fear"]
    message = {"content": "She felt angry. The word fear is also present."}
    assert reported_affect([{"response": {"choices": [{"message": message}]}}]) is None


def test_plan_never_requires_provider_configuration_or_imports_runtime(monkeypatch, capsys):
    monkeypatch.setattr(cli, "execute", lambda *_: pytest.fail("Planning must not execute."))
    monkeypatch.setattr(cli, "preflight", lambda *_: pytest.fail("Planning needs only stdlib."))
    assert cli.main(["plan", "--group", "autonomy"]) == 0
    assert len(json.loads(capsys.readouterr().out)["cases"]) == 5


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.org",
        "https://key@example.org/v1",
        "https://example.org/v1?q=key",
        "https://example.org/v1#key",
        "/v1",
    ],
)
def test_endpoint_rejects_credential_and_ambiguous_urls(value):
    with pytest.raises(ValueError):
        cli.endpoint(value)


def test_preflight_reports_missing_vector_dependency(monkeypatch):
    original = cli.importlib.import_module

    def importing(name):
        if name == "lancedb":
            raise ModuleNotFoundError(name)
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", importing)
    status = cli.preflight()
    assert not status["ready"] and status["missing"] == ["lancedb"]


def test_quota_and_endpoint_check_precede_dispatch():
    recorder = Recorder("https://example.org/v1", 3)
    router = SimpleNamespace(provider="custom_openai", api_base=recorder.endpoint)
    for _ in range(3):
        recorder.reserve(router, {})
    with pytest.raises(RunStoppedError):
        recorder.reserve(router, {})
    assert len(recorder.calls) == 3 and recorder.stopped
    other = Recorder(recorder.endpoint, 3)
    with pytest.raises(RunStoppedError):
        other.reserve(SimpleNamespace(provider="openai"), {})
    assert other.calls == []


async def test_recorder_forwards_native_and_structured_requests_without_rewriting(monkeypatch):
    from backend.core.llm_router import GameMasterLLM

    response = SimpleNamespace(
        model_dump=lambda **_: {
            "choices": [{"message": {"tool_calls": [{"id": "tool-1"}]}}],
            "usage": {"completion_tokens": 8},
        }
    )
    original = AsyncMock(return_value=response)
    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", original)
    recorder = Recorder("https://example.org/v1", 3)
    recorder.install(monkeypatch)
    router = SimpleNamespace(provider="custom_openai", api_base=recorder.endpoint)
    kwargs = {
        "tools": [{"type": "function"}],
        "messages": [{"role": "user", "content": "Test"}],
        "api_key": "DO_NOT_RECORD",
    }
    result = await GameMasterLLM._acompletion_with_openrouter_fallback(router, kwargs)
    assert result is response
    original.assert_awaited_once_with(router, kwargs)
    assert recorder.calls[0]["usage"]["completion_tokens"] == 8
    assert "DO_NOT_RECORD" not in json.dumps(recorder.calls)


async def test_explicit_provider_rejection_does_not_become_an_uncertain_remote_job(monkeypatch):
    from fastapi import HTTPException

    from backend.core.llm_router import GameMasterLLM

    original = AsyncMock(side_effect=HTTPException(400, "Unsupported native tools"))
    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", original)
    recorder = Recorder("https://model.example/v1", 3)
    recorder.install(monkeypatch)
    router = SimpleNamespace(provider="custom_openai", api_base=recorder.endpoint)
    with pytest.raises(HTTPException):
        await GameMasterLLM._acompletion_with_openrouter_fallback(router, {})
    assert not recorder.stopped and recorder.calls[0]["status"] == "rejected"


def test_executor_passes_isolated_environment_and_collects_before_dispatch(monkeypatch):
    commands = []
    monkeypatch.setenv("OPENAI_API_KEY", "UNRELATED_SECRET")
    monkeypatch.setattr(cli, "preflight", lambda: {"ready": True})
    monkeypatch.setattr(cli, "review", lambda args: 0)

    def run(command, **options):
        commands.append((command, options))
        return SimpleNamespace(returncode=0, stdout="a" * 40 if "rev-parse" in command else "")

    monkeypatch.setattr(cli.subprocess, "run", run)
    args = cli._parser().parse_args(
        ["run", "--endpoint", "https://model.example", "--run-id", "isolated", "--max-calls", "5"]
    )
    assert cli.execute(args, manifest([CASES[0]], 1)) == 0
    children = [(command, options) for command, options in commands if "pytest" in command]
    assert len(children) == 2 and "--collect-only" in children[0][0]
    assert "--collect-only" not in children[1][0]
    environment = children[1][1]["env"]
    assert "OPENAI_API_KEY" not in environment
    assert environment["DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"
    assert environment["INFERENCE_SERIALIZATION_ENABLED"] == "true"
    assert environment["TALEWEAVER_LIVE_ENDPOINT"] == "https://model.example/v1"
    assert json.loads(environment["TALEWEAVER_LIVE_MANIFEST"])["engine_revision"] == "a" * 40


class Stream:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True

    async def __aiter__(self):
        yield {"choices": [{"delta": {"content": "one"}}]}
        yield {"usage": {"completion_tokens": 1}}


async def test_stream_preserves_usage_and_records_cancellation_as_uncertain(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    directory = artifacts.create("stream", {})
    recorder = Recorder("https://example.org/v1", 3, directory)
    router = SimpleNamespace(provider="custom_openai", api_base=recorder.endpoint)
    stream = Stream()
    row = recorder.reserve(router, {"stream": True})
    assert len([part async for part in recorder.stream(stream, row, time.monotonic())]) == 2
    assert stream.closed and not recorder.stopped
    assert artifacts.records(directory, "calls.jsonl")[0]["usage"] == {"completion_tokens": 1}
    row = recorder.reserve(router, {"stream": True})
    iterator = recorder.stream(Stream(), row, time.monotonic())
    await anext(iterator)
    await iterator.aclose()
    assert row["status"] == "incomplete_stream" and recorder.stopped


def test_artifacts_refuse_traversal_symlink_and_oversized_append(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "ROOT", tmp_path / "root")
    with pytest.raises(ValueError):
        artifacts.folder("../outside")
    directory = artifacts.create("safe", {})
    outside = tmp_path / "outside"
    outside.write_text("preserved")
    artifacts.target(directory, "calls.jsonl").symlink_to(outside)
    with pytest.raises(ValueError):
        artifacts.append(directory, "calls.jsonl", {})
    assert outside.read_text() == "preserved"
    monkeypatch.setattr(artifacts, "MAX_BYTES", 3)
    with pytest.raises(ValueError):
        artifacts.append(directory, "results.jsonl", {"large": "payload"})


def result_fixture():
    return {
        "case_id": "emotions-concealed-live",
        "repetition": 1,
        "turn": 1,
        "group": "emotions",
        "scenario": "concealed",
        "mode": "live",
        "input": "An uncertain report arrives.",
        "completed": True,
        "errors": [],
        "messages": [{"content": "Lina smiles while concealing worry."}],
        "before": {"state": {"entity_states": {}}},
        "after": {"state": {"entity_states": {}}},
    }


def test_pending_review_is_unknown_and_blind_document_hides_self_report():
    row = result_fixture()
    rating = review.Rating(sample_id=review.identifier(row), result_hash=review.fingerprint(row))
    stats = review.statistics([row], [rating])
    assert stats["reviewed_samples"] == 0 and stats["pending_samples"] == 1
    assert stats["independent_label_counts"] is None
    assert stats["internal_exact_set_agreement"] is None
    document = review.blind_document([row])
    assert row["case_id"] not in document and '"entity_states"' not in document


def test_review_rejects_fabricated_quotes_and_changed_results():
    row = result_fixture()
    rating = review.Rating(
        sample_id=review.identifier(row),
        result_hash=review.fingerprint(row),
        evidence_quotes=["Absent quote"],
    )
    with pytest.raises(ValueError, match="quote"):
        review.statistics([row], [rating])
    rating.evidence_quotes = []
    changed = {**row, "input": "Changed context"}
    with pytest.raises(ValueError, match="modified"):
        review.statistics([changed], [rating])


def test_review_keeps_independent_disagreement_and_does_not_make_it_a_runtime_failure():
    row = {**result_fixture(), "model_reported_affect": ["anger"], "mode": "live"}
    rating = review.Rating(
        sample_id=review.identifier(row),
        result_hash=review.fingerprint(row),
        status="reviewed",
        inferred_internal=["fear"],
        narrated=["fear"],
        dialogue=[],
        evidence_quotes=[row["messages"][0]["content"]],
        contextually_grounded=True,
        initiative=False,
        unnecessary_permission=False,
        preserves_player_agency=True,
        action_matches_state=True,
    )
    stats = review.statistics([row], [rating])
    assert stats["internal_exact_set_agreement"] == 0
    assert stats["technical_failures"] == 0
    assert stats["conditions"]["live"]["narrated_label_counts"] == {"fear": 1}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_all_synthetic_sessions_validate_without_provider_calls(case, monkeypatch):
    monkeypatch.delenv("TALEWEAVER_LIVE_API_KEY", raising=False)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, case, {}, 4096)
        value = await snapshot(db)
        assert user.encrypted_api_keys == {}
        assert value["state"]["current_scene_id"] == "START"
        assert value["notebooks"]["ABSENT"]["revision"] == 1
        assert len(value["avatar"]["inventory"]) == 2


async def test_full_vn_orchestration_produces_current_reply_only_offline(monkeypatch):
    from tests.live_contracts import run_turn
    from tests.test_vn_turn_integration import NARRATION, TurnRoles, install_roles

    install_roles(monkeypatch, TurnRoles())
    case = next(case for case in CASES if case.id == "emotions-overt-off")
    async with TestSessionLocal() as db:
        user, state = await prepare(db, case, {}, 4096)
        runtime = SimpleNamespace(recorder=Recorder("https://example.org/v1", 10))
        result = await run_turn(db, user, case, ACTIONS[case.scenario][0], 1, 1, runtime)
        assert result["completed"] and result["errors"] == []
        assert [row["content"] for row in result["messages"]] == [NARRATION]
        assert result["calls"] == []  # Explicit role doubles: this is not a live quality result.
