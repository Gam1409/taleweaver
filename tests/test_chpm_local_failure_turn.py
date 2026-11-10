"""One completed bad NPC proposal cannot erase a separately reviewed decision."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import continuation_writer, inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.chpm_projection_fixture import public_projection
from tests.conftest import TestSessionLocal
from tests.test_chpm_kernel import preferred_choice, wire_proposal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


class LocalFailureRoles(ChpmRoles):
    def __init__(self):
        super().__init__()
        self.bad_actors = set()
        self.reviews = []
        self.requests = []
        self.reject_reviews = 0
        self.failure_kind = "schema"
        self.initiate_then_continue = False
        self.with_portraits = False

    @property
    def story(self):
        lines = {
            "LINA": "Лина: «Я готова обсудить следующий шаг.»",
            "MILA": "Мила: «Я продолжу разговор.»",
        }
        return (
            "\n".join(line for actor, line in lines.items() if actor not in self.bad_actors)
            or "В комнате повисла тишина."
        )

    async def simple(self, system, payload, model, **kwargs):
        phase, supplied = kwargs.get("phase"), json.loads(payload)
        self.requests.append((phase, supplied.get("actor_id")))
        if phase == "perception":
            result = public_projection(supplied)
            for fragment in result["fragments"].values():
                fragment["engaged"] = fragment["observers"]
            return json.dumps(result)
        if phase in {"proposal", "proposal_repair"}:
            return self.propose(supplied)
        if phase == "validation":
            return self.review(supplied)
        replies = {
            "repair": "Мила: «Давай спокойно продолжим обсуждение.»",
            "rp_continuation": "За окном негромко шумел дождь. В комнате стало тихо.",
        }
        if phase in replies:
            return replies[phase]
        return await super().simple(system, payload, model, **kwargs)

    def propose(self, supplied):
        bad = supplied["actor_id"] in self.bad_actors
        if bad and self.failure_kind == "schema":
            return '{"candidates":{}}'
        result = wire_proposal()
        result["choice"] = preferred_choice(supplied)
        if self.initiate_then_continue and not supplied.get("previous_intention"):
            result["candidates"]["INITIATE"] = result["candidates"].pop("CONTINUE")
            result["choice"]["preferred"] = "INITIATE"
        if bad:
            result["choice"]["continuity"] = "new"
        return json.dumps(result)

    def review(self, supplied):
        self.reviews.append(supplied)
        if self.reject_reviews:
            self.reject_reviews -= 1
            return json.dumps(
                {
                    "matches": False,
                    "issues": ["The proposed interaction contradicts the shared scene."],
                }
            )
        names = {"LINA": "Лина:", "MILA": "Мила:"}
        return json.dumps(
            {
                "matches": True,
                "evidence": [
                    {
                        "actor_id": actor,
                        "passage_id": next(
                            key
                            for key, text in supplied["passages"].items()
                            if names[actor] in text
                        ),
                    }
                    for actor in supplied["controlled_actor_ids"]
                ],
            }
        )

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))

        async def chunks():
            content = self.story
            if self.with_portraits:
                content += '<npc-state>{"npcs":[{"npc_id":"LINA","emotion":"fear","intensity":80,"thought":"An unconfirmed new thought."},{"npc_id":"MILA","emotion":"interest","intensity":60,"thought":"I can explain my point."}]}</npc-state>'
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=content))])

        return chunks()


async def seed_pair(db, *, concurrency=1, policy="continue"):
    user, _, state, _ = await seed_vn(db)
    db.add(
        WorldEntity(
            id="MILA",
            session_id="session-1",
            entity_type="NPC",
            name="Мила",
            description="A traveler in a green coat.",
            current_scene_id="START",
            character="Values independence.",
            goal="Continue this discussion.",
        )
    )
    state.entity_states = {
        **state.entity_states,
        KEY: KernelState(
            settings=Settings(
                mode="live",
                actor_ids=["LINA", "MILA"],
                npc_concurrency=concurrency,
                max_calls_per_turn=7,
                failure_policy=policy,
            )
        ).model_dump(),
    }
    await db.commit()
    return user, state


def install(monkeypatch, roles):
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    monkeypatch.setattr(continuation_writer, "GameMasterLLM", roles)


async def play(db, user, text=ACTION):
    host = GameTurnManager(db, "session-1", user)
    events = [event async for event in host.process_turn(text)]
    assert not any(event.startswith("event: error") for event in events), "".join(events)
    assert any(event.startswith("event: final") for event in events), "".join(events)
    return host, events


@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("bad", ["LINA", "MILA"])
@pytest.mark.parametrize("failure_kind", ["schema", "semantic"])
async def test_rejected_npc_proposal_preserves_the_other_reviewed_update(
    monkeypatch, concurrency, bad, failure_kind
):
    roles = LocalFailureRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db, concurrency=concurrency)
        host, _ = await play(db, user)
        before = load(host.state).model_copy(deep=True)
        assert set(before.minds) == {"LINA", "MILA"}
        roles.bad_actors = {bad}
        roles.failure_kind = failure_kind
        roles.requests.clear()
        host, events = await play(db, user, "Пожалуйста, продолжайте разговор.")
        await db.refresh(state)
        saved = load(state)
        good = "MILA" if bad == "LINA" else "LINA"
        assert saved.actors[good].reply_id != before.actors[good].reply_id
        assert saved.minds[good] != before.minds[good]
        assert saved.actors[bad] == before.actors[bad]
        assert saved.minds[bad] == before.minds[bad]
        assert saved.memories[bad] == before.memories[bad]
        assert saved.last_active[bad] == before.last_active[bad]
        assert not saved.usage.simplified and saved.usage.status == "validated"
        assert set(saved.usage.actor_failures) == {bad}
        assert saved.usage.calls == 5 and saved.usage.proposal_repairs == 1
        assert set(roles.reviews[-1]["contract"]) == {good}
        assert set(roles.reviews[-1]["inactive_controlled_actors"]) == {bad}
        assert KernelState.model_validate_json(saved.model_dump_json()) == saved
        final = json.loads(
            next(e for e in events if e.startswith("event: final")).split("data: ")[1]
        )
        assert final["npc_behavior"]["quality"] == "partial"
        reply = await db.get(ChatMessage, saved.actors[good].reply_id)
        assert reply.content == roles.story
        assert "INACTIVE CHPM CHARACTERS" in str(roles.prompts[-1])
        assert state.current_scene_id == "START"


@pytest.mark.parametrize("rejections", [1, 2])
async def test_partial_proposals_still_need_the_shared_scene_review(monkeypatch, rejections):
    roles = LocalFailureRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db)
        host, _ = await play(db, user)
        before = load(host.state).model_copy(deep=True)
        roles.bad_actors = {"LINA"}
        roles.reject_reviews = rejections
        reviews_before = len(roles.reviews)
        _, events = await play(db, user, "Давайте продолжим.")
        await db.refresh(state)
        saved = load(state)
        assert len(roles.reviews) == reviews_before + 2
        assert saved.minds["LINA"] == before.minds["LINA"]
        assert saved.usage.repairs == 1
        if rejections == 1:
            assert saved.actors["MILA"].reply_id != before.actors["MILA"].reply_id
            assert not saved.usage.simplified
            reply = await db.get(ChatMessage, saved.actors["MILA"].reply_id)
            assert reply.content == "Мила: «Давай спокойно продолжим обсуждение.»"
        else:
            assert saved.actors == before.actors and saved.minds == before.minds
            assert saved.usage.simplified and saved.usage.fallback_reason == "review_rejected"
            assert saved.usage.fallback_requests == 1
        assert any(event.startswith("event: final") for event in events)


async def test_live_shaped_initiation_to_continuation_survives_a_peers_local_failure(monkeypatch):
    roles = LocalFailureRoles()
    roles.initiate_then_continue = True
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db)
        host, _ = await play(db, user)
        before = load(host.state)
        assert before.actors["MILA"].selected.kind == "INITIATE"
        roles.bad_actors = {"LINA"}
        host, _ = await play(db, user, "Мила, продолжай ту же тему.")
        saved = load(host.state)
        assert not saved.usage.simplified and saved.usage.status == "validated"
        assert saved.actors["MILA"].selected.kind == "CONTINUE"
        assert saved.actors["MILA"].choice_preference.continuity == "maintain"
        assert saved.usage.proposal_repairs == 1
        assert saved.minds["LINA"] == before.minds["LINA"]


async def test_only_the_paused_npcs_new_thoughts_and_emotions_are_excluded(monkeypatch):
    from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY

    roles = LocalFailureRoles()
    roles.with_portraits = True
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db)
        state.entity_states = {
            **state.entity_states,
            PORTRAIT_KEY: {"emotion_palette": True, "character_thoughts": True},
        }
        await db.commit()
        host, _ = await play(db, user)
        before = load(host.state)
        roles.bad_actors = {"LINA"}
        host, _ = await play(db, user, "Мила, расскажи чуть подробнее.")
        saved = load(host.state)
        reply = await db.get(ChatMessage, saved.actors["MILA"].reply_id)
        assert set(reply.portrait_state["npcs"]) == {"MILA"}
        assert reply.portrait_state["npcs"]["MILA"]["thought"] == "I can explain my point."
        assert saved.minds["LINA"] == before.minds["LINA"]


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_strict_policy_rolls_back_instead_of_publishing_a_partial_turn(
    monkeypatch, concurrency
):
    roles = LocalFailureRoles()
    roles.bad_actors = {"MILA"}
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db, concurrency=concurrency, policy="strict")
        before = deepcopy(state.entity_states)
        host = GameTurnManager(db, "session-1", user)
        events = [event async for event in host.process_turn(ACTION)]
        assert any(e.startswith("event: error") for e in events)
        assert not any(e.startswith(("event: final", "event: chunk")) for e in events)
        await db.refresh(state)
        assert state.entity_states == before
        replies = list(await db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant")))
        assert len(replies) == 1
