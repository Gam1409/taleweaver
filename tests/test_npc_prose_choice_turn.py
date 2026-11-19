"""One actor-authored sentence can offer a garment, give it, or describe no present act."""

import json

import pytest

from backend.engine.chpm.state import load
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.visuals import session_objects
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, content_hash
from backend.engine.visual_novel.continuity import SCENE
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.npc_sequential_fixture import COAT, PLAN, owner_state, seed_sequential
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_two_phase_turn import CUP, CupRoles, assert_committed, reload

CASES = {
    "offer": (
        "I'll take off my coat and hold it out to Mila, in case she wants it.",
        "Лина: «Возьмёшь?»\nЛина сняла пальто и протянула его Миле, ожидая ответа.",
    ),
    "give": (
        "I'll take off my coat and hand it to Mila.",
        "Лина: «Держи.»\nЛина сняла пальто и передала его Миле.",
    ),
    "past": ("I remember taking off the coat yesterday.", "Лина: «Я вчера снимала пальто.»"),
    "future": (
        "I promise Mila that I'll give her the coat when we leave tomorrow.",
        "Лина: «Мила, обещаю отдать тебе пальто завтра, перед отъездом.»",
    ),
    "negated": (
        "I considered taking off the coat, but changed my mind.",
        "Лина: «Я хотела снять пальто, но передумала.»",
    ),
    "incidental": (
        "I hesitate as I search for the right word.",
        "Лина помедлила, подбирая слова.\nЛина: «Как же это выразить?»",
    ),
    "ambiguous": ("I'll pick up the copper cup.", "Лина: «Которую из двух?»"),
    "round_trip": (
        "I pick up the copper cup on the desk and put it back in the same place.",
        "Лина: «Та же кружка.»\nЛина подняла кружку и поставила её обратно.",
    ),
    "unsupported": ("I wish to make a new chair appear under me.", "Лина: «Придётся постоять.»"),
}


class SourceRoles(CupRoles):
    def __init__(self, case):
        super().__init__([])
        self.case = case
        self.source_calls = []

    @property
    def story(self):
        return CASES[self.case][1]

    def answer(self, payload, functions, phase, kwargs):
        if phase != "npc_execution":
            result = super().answer(payload, functions, phase, kwargs)
            selection = result[0][1]
            source = CASES[self.case][0]
            refs = {"offer": [COAT, "MILA"], "give": [COAT, "MILA"], "round_trip": [CUP]}
            step = {"text": source, "target_refs": refs[self.case]} if self.case in refs else source
            selection["physical_intent"] = {"mode": "act", "steps": [step]}
            return result
        self.source_calls.append(payload)
        group = {"passage_id": "p0"}
        if self.case == "offer":
            group.update(disposition="action", actions=PLAN[:1], remainder="offer")
        elif self.case == "give":
            group.update(disposition="action", actions=PLAN)
        elif self.case == "round_trip":
            group.update(
                disposition="action",
                actions=[{"tool": tool, "item_id": CUP} for tool in ("take_item", "put_down_item")],
            )
        elif self.case == "unsupported":
            group.update(disposition="unresolved", reason="unsupported_effect")
        elif self.case == "ambiguous":
            # The technically valid ID was guessed by the translator. Both cups
            # were visible, and the actor's source did not distinguish them.
            group.update(disposition="action", actions=[{"tool": "take_item", "item_id": CUP}])
        else:
            group.update(disposition="no_effect", reason=self.case)
        return [("resolve_selected_steps", {"resolutions": [group]})]


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("case", CASES)
async def test_selected_prose_matches_publication_after_reload(monkeypatch, case, protocol):
    roles = SourceRoles(case)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        if case == "ambiguous":
            db.add(
                WorldEntity(
                    id="OTHER_CUP",
                    session_id=session_id,
                    entity_type="OBJECT",
                    name="Copper cup",
                    description="A single loose cup.",
                    current_scene_id="START",
                    is_portable=True,
                )
            )
            await db.commit()
        _, events = await run(db, user, "I listen, leaving the decision to you.")
        assert_committed(events)
    assert roles.source_calls
    output = "".join(
        json.loads(row.partition("\ndata: ")[2])["content"]
        for row in events
        if row.startswith("event: chunk")
    )
    async with TestSessionLocal() as db:
        _, host, possessions = await reload(db, session_id, user_id)
        decision = load(host.state).actors["LINA"]
        reply = await db.get(ChatMessage, decision.reply_id)
        snapshot = host.state.entity_states[REGISTRY_KEY]["snapshots"][reply.id]
        assert roles.story == output == reply.content == snapshot["narration"]
        assert snapshot["content_hash"] == content_hash(reply)
        acknowledgment = decision.last_publication
        execution = acknowledgment.execution
        source = execution.source_selection
        assert [p.text for p in source.selection.passages] == [CASES[case][0]]
        assert source.selection.control.actor_id == "LINA"
        assert source.selection.control.attempt_id == acknowledgment.attempt_id
        expected = {
            "give": ["take_off_item", "give_item"],
            "offer": ["take_off_item"],
            "round_trip": ["take_item", "put_down_item"],
        }
        assert [row.tool for row in acknowledgment.operations] == expected.get(case, [])
        assert all(row.status == "applied" for row in acknowledgment.operations)
        if case in expected:
            [resolved] = source.resolutions
            assert execution.status == "staged" and resolved.passage_id == "p0"
            assert [step.operation_id for step in resolved.actions] == [
                row.operation_id for row in acknowledgment.operations
            ]
            assert resolved.remainder == ("offer" if case == "offer" else None)
        elif case in {"ambiguous", "unsupported"}:
            assert execution.status == "rejected"
            code = "ambiguous_target" if case == "ambiguous" else "unsupported_effect"
            assert any(error.code == code for error in execution.gate_errors)
        else:
            [resolved] = source.resolutions
            assert execution.status == "no_effect"
            assert (resolved.passage_id, resolved.disposition, resolved.reason) == (
                "p0",
                "no_effect",
                case,
            )
        assert await owner_state(host) == (
            "MILA" if case == "give" else "LINA",
            set() if case in {"give", "offer"} else {COAT},
        )
        recipient = actor_records(host, await session_objects(db, session_id))["MILA"]
        outfit = load_profile(recipient["visual_profile"])
        assert not outfit or all(row.item_id != COAT for row in outfit.worn)
        if case == "ambiguous":
            assert possessions.owners[CUP] == possessions.owners["OTHER_CUP"] == SCENE
        if case == "round_trip":
            assert possessions.owners[CUP] == SCENE
