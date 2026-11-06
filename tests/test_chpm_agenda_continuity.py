"""Unfinished business reaches the writer beyond the transient dialogue window."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import context, inference, rendering, runtime
from backend.engine.chpm.schema import AgendaClosure, KernelState, Settings
from backend.engine.chpm.state import KEY, load
from tests.conftest import TestSessionLocal
from tests.test_chpm_agenda import undertaking
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_memory import source
from tests.test_chpm_runtime import manager
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, NARRATION, install_roles, seed_vn

GOAL = "Deliver the collected sample to the laboratory"
PROMISE = "Я отнесу уже взятую пробу в лабораторию."
SAMPLE = "Лина убрала уже взятую пробу во внутренний карман халата для анализа в лаборатории."


def test_writer_and_reviewer_keep_all_open_owned_goals_even_when_not_selected_as_motives():
    turn, _ = contract_fixture()
    closed = undertaking(identifier="closed", text="Already finished")
    closed.closure = AgendaClosure(reason="report_done", source=closed.source)
    records = [
        undertaking(identifier=f"goal-{index}", text=f"Open task {index}") for index in range(8)
    ]
    turn.agendas["npc"] = [
        *records,
        closed,
        undertaking(actor="other", text="Private foreign plan"),
    ]
    before = [entry.model_dump_json() for entry in turn.agendas["npc"]]
    data = runtime.contract_data(turn)["npc"]
    pending = data["ongoing_agenda_not_world_facts"]
    assert [entry["text"] for entry in pending] == [entry.text for entry in records]
    assert all(set(entry) == {"id", "kind", "text"} for entry in pending)
    assert (
        rendering._review_payload(turn, {}, "")["contract"]["npc"]["ongoing_agenda_not_world_facts"]
        == pending
    )
    assert "Private foreign plan" not in runtime.contract(turn)
    assert "Already finished" not in runtime.contract(turn)
    assert before == [entry.model_dump_json() for entry in turn.agendas["npc"]]


@pytest.mark.parametrize("invalid", [None, "session", "revision", "missing"])
async def test_cooldown_keeps_source_checked_goals_without_model_calls(monkeypatch, invalid):
    host, actor = manager()
    current = load(host.state)
    current.settings.failure_policy = "continue"
    current.settings.memory_limit = 0
    current.recovery.cooldown_remaining = 1
    current.agenda = [undertaking()]
    host.state.entity_states[KEY] = current.model_dump()
    message = source()
    if invalid == "session":
        message.session_id = "foreign"
    if invalid == "revision":
        message.revision_id = "edited"
    host.db = SimpleNamespace(
        scalars=AsyncMock(return_value=[] if invalid == "missing" else [message])
    )
    monkeypatch.setattr(context, "available", lambda *_: True)
    request = AsyncMock(side_effect=AssertionError("No inference during cooldown"))
    monkeypatch.setattr(inference, "request", request)
    result = await runtime.prepare(host, "A different topic", [actor])
    data = json.loads(result[result.index("{") :])
    pending = data["npc_identities"]["npc"]["ongoing_agenda_not_world_facts"]
    assert bool(pending) == (invalid is None)
    if pending:
        assert pending[0]["text"] == "Repair the bridge"
    request.assert_not_awaited()
    assert load(host.state).agenda == current.agenda


class LongAgendaRoles(ChpmRoles):
    """Keep choosing an unrelated conversation; never cite the old goal as a motive."""

    def __init__(self):
        super().__init__()
        self.complete = False
        self.reviews = []

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            self.chpm_calls.append("validation")
            data = json.loads(payload)
            self.reviews.append(data["contract"]["LINA"])
            evidence = {
                "actor_id": "LINA",
                "passage_id": next(iter(data["passages"])),
            }
            changed = len(self.proposal_inputs) == 1 or self.complete
            causal = []
            if len(self.proposal_inputs) == 1:
                reference = next(
                    key for key, passage in data["passages"].items() if SAMPLE in passage
                )
                causal = [
                    {
                        "actor_id": "LINA",
                        "action": "open",
                        "facts": {
                            "purpose": {
                                "text": "Have the collected sample analysed",
                                "passage_id": reference,
                            },
                            "cause": {
                                "text": "A sample has already been collected",
                                "passage_id": reference,
                            },
                            "consequence": {
                                "text": "The sample is in Lina's inner coat pocket",
                                "passage_id": reference,
                            },
                        },
                    }
                ]
            if self.complete:
                thread = data["contract"]["LINA"]["causal_continuity_not_world_facts"][0]
                causal = [
                    {
                        "actor_id": "LINA",
                        "action": "close",
                        "thread_id": thread["id"],
                        "facts": {
                            "consequence": {
                                "text": "Lina delivered the sample for analysis",
                                "passage_id": evidence["passage_id"],
                            }
                        },
                    }
                ]
            return json.dumps(
                {
                    "matches": True,
                    "evidence": [evidence],
                    "agenda_evidence": [evidence] if changed else [],
                    "causal_updates": causal,
                }
            )
        result = json.loads(await super().simple(system, payload, model, **kwargs))
        if kwargs.get("phase") != "proposal":
            return json.dumps(result)
        change = None
        if len(self.proposal_inputs) == 1:
            change = {"action": "commitment", "text": GOAL}
        if self.complete:
            active = self.proposal_inputs[-1]["declared_agenda_not_world_facts"][0]
            change = {"action": "report_done", "text": GOAL, "entry_id": active["id"]}
        result["candidates"]["CONTINUE"]["agenda_change"] = change
        return json.dumps(result)

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        text = f'Лина: "{PROMISE}"' if len(self.proposal_inputs) == 1 else NARRATION
        if len(self.proposal_inputs) == 1:
            text += "\n\n" + SAMPLE
        if self.complete:
            text = 'Лина: "Я уже отдала пробу в лабораторию для анализа."'

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=text))])

        return chunks()


async def test_twenty_unrelated_turns_and_zero_recall_do_not_hide_or_complete_a_promise(
    monkeypatch,
):
    roles = LongAgendaRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=Settings(
                    mode="live", actor_ids=["LINA"], memory_limit=0, failure_policy="strict"
                )
            ).model_dump(),
        }
        await db.commit()
        for index in range(22):
            roles.complete = index == 21
            host = GameTurnManager(db, "session-1", user)
            chunks = [part async for part in host.process_turn(ACTION)]
            assert any(part.startswith("event: final") for part in chunks), "".join(chunks)
            saved = load(host.state)
            assert len(saved.agenda) == 1 and saved.memories["LINA"] == []
            assert bool(saved.agenda[0].closure) == roles.complete
            thread = saved.causal_memory.actors["LINA"][0]
            assert bool(thread.closure) == roles.complete
            if not roles.complete:
                assert (
                    thread.facts["consequence"].text == "The sample is in Lina's inner coat pocket"
                )
            if index:
                assert roles.reviews[-1]["ongoing_agenda_not_world_facts"][0]["text"] == GOAL
                assert GOAL in json.dumps(roles.prompts[-1], ensure_ascii=False)
                assert (
                    roles.proposal_inputs[-1]["declared_agenda_not_world_facts"][0]["text"] == GOAL
                )
                causal = roles.proposal_inputs[-1]["causal_continuity_not_world_facts"]
                assert (
                    causal[0]["facts"]["consequence"] == "The sample is in Lina's inner coat pocket"
                )
                evidence = roles.proposal_inputs[-1]["appraisal_context"]["visible_evidence"]
                assert any(
                    item["text"] == SAMPLE and item["channel"] == "narration"
                    for item in evidence
                    if "channel" in item
                )
            assert saved.usage.causal_notes == []
            # No additional extraction, recall or TODO model request.
            assert saved.usage.calls == 3
        assert saved.agenda[0].closure.reason == "report_done"
