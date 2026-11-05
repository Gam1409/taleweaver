"""Regression coverage for failures observed with the live model, without network calls."""

import json
from types import SimpleNamespace

import pytest
from pydantic import Field

from backend.engine.chpm import (
    appraisal_context,
    motivation,
    perception_fragments,
    proposal_attempt,
    rendering,
)
from backend.engine.chpm.evaluation import matrix_runner, memory_stress
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Contract, Settings, Usage
from tests.test_chpm_appraisal import heard
from tests.test_chpm_matrix import Models
from tests.test_chpm_motivation import candidates, catalogue
from tests.test_chpm_runtime import prepared


def classified(available, kinds):
    return perception_fragments.Projection.model_validate(
        {
            "fragments": {
                key: {
                    "kind": kind,
                    "observers": ["npc"] if kind in perception_fragments.PUBLIC else [],
                    "engaged": ["npc"] if kind in {"speech", "attempt"} else [],
                }
                for key, kind in zip(available, kinds, strict=True)
            }
        }
    )


def test_short_speech_and_attempt_survive_many_gestures_and_private_thought():
    message = "I adjust a strap. I move my cup. I smooth my sleeve. Well? I try the locked handle. My private thought is SECRET."
    available = perception_fragments.index(message)
    raw = classified(
        available, ["incidental", "incidental", "incidental", "speech", "attempt", "private"]
    )
    view = perception_fragments.resolve(raw, available, {"npc"})["npc"]
    assert "Well?" in view.quotes
    assert "I try the locked handle." in view.quotes
    assert "attempt" in view.quote_kinds
    assert "SECRET" not in "\n".join(view.quotes)
    assert len(view.coverage) == len(available)
    assert "incidental_budget" in view.coverage.values()


@pytest.mark.parametrize("failure", ["missing", "invented", "private_exposed", "foreign"])
def test_incomplete_or_invalid_fragment_classification_cannot_be_used(failure):
    available = perception_fragments.index("Well? I try a handle.")
    raw = classified(available, ["speech", "attempt"]).model_dump()
    if failure == "missing":
        raw["fragments"].pop("p0")
    elif failure == "invented":
        raw["fragments"]["ghost"] = raw["fragments"]["p0"]
    elif failure == "private_exposed":
        raw["fragments"]["p0"]["kind"] = "private"
    else:
        raw["fragments"]["p0"]["observers"] = ["absent"]
    with pytest.raises(ChpmError):
        perception_fragments.resolve(
            perception_fragments.Projection.model_validate(raw), available, {"npc"}
        )


def test_fragment_overflow_is_explicit_and_never_truncated():
    with pytest.raises(ChpmError, match="split this dense message"):
        perception_fragments.index("Yes. " * 33)
    with pytest.raises(ChpmError, match="6000 characters"):
        perception_fragments.index("x" * 6001)


def test_current_and_historical_sources_are_explicit_and_ordered():
    mind = heard(text="An old promise.")
    mind = heard(mind, "m2", "A current offer.")
    before = mind.model_dump_json()
    window = appraisal_context.build(mind, current_message_id="m2")
    entries = window.payload["visible_evidence"]
    assert [entry["current_turn"] for entry in entries] == [False, True]
    assert [entry["source_message_id"] for entry in entries] == ["m1", "m2"]
    assert entries[0]["evidence_order"] < entries[1]["evidence_order"]
    assert mind.model_dump_json() == before


def test_goal_judgment_is_derived_without_trusting_retired_model_fields():
    raw = candidates().model_dump()
    raw["choice"] = {
        "preferred": "ACCEPT",
        "motive_ids": ["goal1"],
        "reason": "Preserve bridge safety",
        "continuity": "new",
    }
    raw["candidates"]["ACCEPT"]["goal_alignment"] = "tension"
    raw["candidates"]["ACCEPT"]["goal_quote"] = "Invented goal"
    draft = Draft.model_validate(raw)
    result = draft.materialize(catalogue())
    assert result.candidates["ACCEPT"].goal_alignment == "supports"
    assert result.candidates["ACCEPT"].goal_quote == "Keep bridges safe"
    motivation.resolve(result, catalogue())
    assert "goal_alignment" not in Draft.model_json_schema()["$defs"]["Intent"]["properties"]


class Response(Contract):
    value: str = Field(max_length=10)


class Replies:
    model = "offline"
    max_tokens = 4096
    request_timeout = 1

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def aexecute_simple_task(self, system, content, _model, **kwargs):
        self.requests.append((kwargs["phase"], system, json.loads(content)))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


async def request_replies(responses, *, budget=6, accept=lambda item: item):
    model = Replies(responses)
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    settings = Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=budget)
    result = await proposal_attempt.request(
        manager, settings, usage, "Use the schema.", {"source": "unchanged"}, Response, {}, accept
    )
    return result, usage, model


@pytest.mark.parametrize("invalid", ['{"value":', '{"value":"too long to fit the schema"}'])
async def test_one_completed_invalid_response_is_repaired_with_exact_feedback(invalid):
    result, usage, model = await request_replies([invalid, '{"value":"valid"}'])
    assert result.value == "valid"
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert [r[0] for r in model.requests] == ["proposal", "proposal_repair"]
    assert model.requests[1][2]["source"] == "unchanged"
    assert model.requests[1][2]["proposal_feedback"]["error"]


async def test_semantic_failure_is_rechecked_and_transport_failure_is_not_retried():
    def accept(value):
        if value.value != "current":
            raise ChpmError("Experience needs current evidence.")
        return value.value

    result, usage, _ = await request_replies(
        ['{"value":"old"}', '{"value":"current"}'], accept=accept
    )
    assert result == "current" and usage.proposal_repairs == 1
    with pytest.raises(ChpmError, match="TimeoutError"):
        await request_replies([TimeoutError("secret server detail")])
    with pytest.raises(ChpmError, match="no reserved request budget"):
        await request_replies(['{"value":'], budget=4)
    with pytest.raises(ChpmError, match="remains invalid"):
        await request_replies(['{"value":', '{"value":'])


class RepairModels(Models):
    def __init__(self, repair_valid=True):
        super().__init__()
        self.repair_valid = repair_valid

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        if kwargs["phase"] == "proposal":
            return '{"invalid":'
        if kwargs["phase"] == "proposal_repair":
            if not self.repair_valid:
                return '{"invalid":'
            kwargs["phase"] = "proposal"
        return await super().aexecute_simple_task(system, content, model, **kwargs)


@pytest.mark.parametrize("valid", [True, False])
async def test_retry_uses_real_cognitive_pipeline_and_failed_turn_never_commits(valid):
    case = memory_stress.catalogue()[0]
    result = await matrix_runner.run(case, RepairModels(valid))
    assert result["status"] == ("ok" if valid else "failed"), result["error"]
    assert result["identity_unchanged"] and result["failed_turn_unchanged"]
    assert [call["phase"] for call in result["calls"]].count("proposal_repair") == 1
    if not valid:
        assert result["response"] == ""
        assert all(
            s["before_cursor"] == s["after_cursor"] for s in result["state_changes"].values()
        )


def test_review_payload_contains_each_passage_once_and_preflight_is_read_only():
    host = prepared()
    turn = host._chpm_turn
    before = turn.initial.model_dump_json()
    text = "Unique spoken sentence."
    body = rendering._review_payload(turn, {"p0": text}, "")
    assert json.dumps(body).count(text) == 1
    assert isinstance(body["contract"], dict) and "narration" not in body
    rendering.preflight(turn)
    assert turn.reply_character_budget >= 512
    assert turn.initial.model_dump_json() == before
    turn.initial.settings.max_input_chars = 100
    with pytest.raises(ChpmError, match="before narration"):
        rendering.preflight(turn)


def test_dynamic_identifier_schema_constrains_array_items_and_fragment_keys():
    from backend.engine.chpm.json_contract import response_schema

    schema = response_schema(
        perception_fragments.Projection,
        {
            "observers": ["npc"],
            "engaged": ["npc"],
            "fragments": ["p0", "p1"],
        },
    )
    assert schema["properties"]["fragments"]["propertyNames"]["enum"] == ["p0", "p1"]
    array = schema["$defs"]["Fragment"]["properties"]["observers"]
    assert "enum" not in array
    assert array["items"]["enum"] == ["npc"]


def test_envelope_migration_preserves_old_request_budget_and_identity():
    from backend.engine.chpm.schema import KernelState
    from tests.test_chpm_kernel import decision

    original = KernelState(
        settings=Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=5),
        actors={"npc": decision()},
    )
    raw = original.model_dump()
    raw["schema_version"] = 1
    raw["usage"].pop("proposal_repairs")
    raw["usage"].pop("proposal_feedback")
    raw["actors"]["npc"].pop("perception_audit")
    migrated = KernelState.model_validate(raw)
    assert migrated == original
    assert migrated.schema_version == 6
    assert migrated.settings.max_calls_per_turn == 5
    assert raw["schema_version"] == 1


def test_quoted_short_speech_is_not_joined_to_a_private_thought_tail():
    case = next(c for c in memory_stress.catalogue() if c.id == "short-speech-long-actions")
    fragments = perception_fragments.index(case.message)
    assert '"Well?"' in fragments.values()
    assert all("feelings" not in text for text in fragments.values() if "Well?" in text)
    assert "".join("".join(fragments.values()).split()) == "".join(case.message.split())


async def test_dense_live_fixture_fits_actual_wire_schema_with_repair_reserve():
    case = next(c for c in memory_stress.catalogue() if c.id == "short-speech-long-actions")

    class ObservedModels(Models):
        async def aexecute_simple_task(self, system, content, model, **kwargs):
            result = await super().aexecute_simple_task(system, content, model, **kwargs)
            if kwargs["phase"] != "perception":
                return result
            raw, supplied = json.loads(result), json.loads(content)
            for key, text in supplied["fragments"].items():
                if "Private thought" in text or "cannot know their feelings" in text:
                    raw["fragments"][key] = {"kind": "private", "observers": [], "engaged": []}
            return json.dumps(raw)

    result = await matrix_runner.run(case, ObservedModels())
    assert result["status"] == "ok", result["error"]
    assert all(c["input_chars"] <= 24000 for c in result["calls"])
    assert '"Well?"' in result["perceptions"]["npc-01"]["quotes"]
