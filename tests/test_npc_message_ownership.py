"""World outcomes, NPC message plans and literary realization have distinct owners."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.engine.chpm import continuation_writer, inference, rendering
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.recovery_contracts import RecoveryState
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY
from backend.engine.visual_novel.intent import VNProgressionIntent, to_chat_progression_intent
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_kernel import preferred_choice, wire_proposal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn

POISON = "Lina has decided that naval histories are her favorite books."
PLAN = "Say she prefers travelogues for their accounts of unfamiliar places."
BODY = "Лина: «Мне нравятся путевые очерки: с ними открываешь незнакомые места»."
ORDINARY = "Лина: «Я выбираю сама, что рассказать. Давай поговорим о книгах»."
FOOTER = '<npc-state>{"npcs":[{"npc_id":"LINA","emotion":"interest","intensity":65,"thought":"There is more to this question."}]}</npc-state>'


def message_packet():
    packet = wire_proposal()
    packet["choice"] = preferred_choice()
    for value in packet["candidates"].values():
        value["message_plan"] = value.pop("intention")
    packet["candidates"]["CONTINUE"]["message_plan"] = PLAN
    return packet


def test_world_request_does_not_own_an_npc_dialogue_draft():
    schema = VNProgressionIntent.model_json_schema()
    assert "narrative_description" not in schema["properties"]
    parsed = VNProgressionIntent.model_validate({"narrative_description": POISON})
    assert to_chat_progression_intent(parsed).narrative_description == ""


@pytest.mark.parametrize("kind", ["dialogue", "activity"])
def test_world_beat_cannot_supply_a_second_npc_message_plan(kind):
    parsed = VNProgressionIntent.model_validate(
        {"story_beat": {"npc_id": "LINA", "kind": kind, "purpose": POISON, "action": POISON}}
    )
    assert parsed.story_beat is None


def test_world_departure_carries_only_movement_not_a_personal_answer():
    parsed = VNProgressionIntent.model_validate(
        {
            "story_beat": {
                "npc_id": "LINA",
                "kind": "departure",
                "destination_id": "LIBRARY",
                "purpose": POISON,
                "action": POISON,
            }
        }
    )
    assert parsed.story_beat.destination_id == "LIBRARY"
    assert POISON not in str(parsed.story_beat.model_dump())
    schema = VNProgressionIntent.model_json_schema()
    assert set(schema["$defs"]["WorldDeparture"]["properties"]) == {
        "npc_id",
        "kind",
        "destination_id",
    }


def test_message_plan_reuses_the_existing_canonical_intention_without_a_second_store():
    draft = Draft.model_validate(message_packet())
    assert draft.candidates["CONTINUE"].intention == PLAN
    assert draft.model_dump()["candidates"]["CONTINUE"]["intention"] == PLAN
    properties = Draft.model_json_schema()["$defs"]["Intent"]["properties"]
    assert "message_plan" in properties and "intention" not in properties
    legacy = wire_proposal()
    legacy["choice"] = preferred_choice()
    assert Draft.model_validate(legacy).candidates["CONTINUE"].intention
    packet = message_packet()
    packet["candidates"]["CONTINUE"]["intention"] = "A conflicting legacy field."
    with pytest.raises(ValidationError):
        Draft.model_validate(packet)


class OwnershipRoles(ChpmRoles):
    def __init__(self, reject=False):
        super().__init__(reject=reject)
        self.reviews = []
        self.repair_requests = []
        self.ordinary_requests = []

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            return type(result).model_validate(
                {
                    **result.model_dump(),
                    "narrative_description": POISON,
                    "story_beat": {
                        "npc_id": "LINA",
                        "kind": "dialogue",
                        "purpose": POISON,
                        "action": POISON,
                    },
                }
            )
        return result

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        if phase == "proposal":
            body = json.loads(await super().simple(system, payload, model, **kwargs))
            name = "message_plan" if "appraisal_context" in json.loads(payload) else "intention"
            if name == "message_plan":
                for value in body["candidates"].values():
                    value[name] = value.pop("intention")
            body["candidates"]["CONTINUE"][name] = PLAN
            return json.dumps(body)
        if phase == "validation":
            supplied = json.loads(payload)
            self.reviews.append(supplied)
            if self.reject:
                return json.dumps({"matches": False, "issues": ["A deliberately rejected reply."]})
            passage = next(
                key for key, value in supplied["passages"].items() if "Мне нравятся" in value
            )
            return json.dumps(
                {"matches": True, "evidence": [{"actor_id": "LINA", "passage_id": passage}]}
            )
        if phase == "repair":
            self.repair_requests.append(json.loads(payload))
            return BODY + FOOTER
        if phase == "rp_continuation":
            self.ordinary_requests.append(json.loads(payload))
            return ORDINARY + FOOTER
        return await super().simple(system, payload, model, **kwargs)

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=BODY + FOOTER))])

        return chunks()


@pytest.mark.parametrize(
    "mode,recovery",
    [("off", ""), ("shadow", ""), ("live", ""), ("live", "cooldown"), ("live", "replacement")],
)
async def test_the_active_writer_gets_only_its_own_message_authority(monkeypatch, mode, recovery):
    roles = OwnershipRoles(reject=recovery == "replacement")
    install_roles(monkeypatch, roles)
    for module in (inference, rendering, continuation_writer):
        monkeypatch.setattr(module, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        kernel = KernelState(settings=Settings(mode=mode, actor_ids=["LINA"]))
        if recovery == "cooldown":
            kernel.recovery = RecoveryState(cooldown_remaining=1)
        state.entity_states = {
            **state.entity_states,
            KEY: kernel.model_dump(),
            PORTRAIT_KEY: {"emotion_palette": True, "character_thoughts": True},
        }
        await db.commit()
        host = GameTurnManager(db, state.session_id, user)
        events = [event async for event in host.process_turn("Which books do you prefer?")]
        assert final_payload(events)["status"] == "success", "".join(events)
        context = json.dumps(roles.prompts[0], ensure_ascii=False)
        assert POISON not in context
        assert (PLAN in context) is (mode == "live" and recovery != "cooldown")
        if mode == "live" and not recovery:
            saved = load(host.state)
            assert saved.actors["LINA"].selected.intention == PLAN
            assert roles.reviews[-1]["contract"]["LINA"]["intention"] == PLAN
            assert roles.reviews[-1]["player_request"] == "Which books do you prefer?"
            assert any(
                "Мне нравятся" in source.text for source in saved.minds["LINA"].sources.values()
            )
        if recovery == "replacement":
            assert roles.repair_requests[0]["player_request"] == "Which books do you prefer?"
            ordinary = json.dumps(roles.ordinary_requests[0], ensure_ascii=False)
            assert PLAN not in ordinary and POISON not in ordinary
        reply = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == state.session_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
        )
        assert reply.content == (ORDINARY if recovery == "replacement" else BODY)
        assert reply.to_client_dict()["portrait_state"]["npcs"]["LINA"]["emotion"] == "interest"
        assert len(roles.prompts) == 1
