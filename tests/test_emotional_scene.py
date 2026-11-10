"""Real VN turns with authored model replies: fidelity, context and factual repair."""

import json
from types import SimpleNamespace

import pytest

from backend.core.npc_presentation import source_hash
from backend.engine.chpm.state import load
from backend.engine.gameplay.turn_prompt_layout import format_recent_narration
from backend.models.chat import ChatMessage
from tests import test_custom_openai as endpoint_fixtures
from tests.conftest import TestSessionLocal
from tests.emotional_scene_fixture import BEATS, IDENTITIES, seed_emotional_scene
from tests.test_chpm_kernel import preferred_choice
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install, play
from tests.test_narrative_fidelity import response

local_policy = endpoint_fixtures.local_policy
pytestmark = pytest.mark.usefixtures("local_policy")
WRONG_LOCATION = "Лина уже стояла у северного моста."
INTENTIONS = {
    "LINA": "Continue seeking truthful news about Oleg and express hurt at the concealment.",
    "MILA": "Continue supporting Lina while demanding accurate news about Oleg.",
}


class EmotionalRoles(LocalFailureRoles):
    """Only provider output and technical model judgements are controlled, never host state."""

    def __init__(self, size, repair):
        super().__init__()
        self.beat = 0
        self.size = size
        self.inject_wrong_location = repair
        self.narrator_requests = []
        self.proposal_inputs = []
        self.repair_inputs = []

    @property
    def story(self):
        return BEATS[self.beat].body

    def footer(self):
        return (
            "<npc-state>"
            + json.dumps(
                {
                    "npcs": [
                        {"npc_id": actor, "emotion": cue[0], "intensity": cue[1], "thought": cue[2]}
                        for actor, cue in BEATS[self.beat].cues.items()
                    ]
                },
                ensure_ascii=False,
            )
            + "</npc-state>"
        )

    def propose(self, supplied):
        self.proposal_inputs.append(supplied)
        body = json.loads(super().propose(supplied))
        body["choice"] = preferred_choice(supplied)
        actor = supplied["actor_id"]
        candidate = body["candidates"]["CONTINUE"]
        candidate["intention"] = INTENTIONS[actor]
        candidate["goal_quote"] = supplied["authored_goal"]
        trigger = [
            row
            for row in supplied["appraisal_context"]["visible_evidence"]
            if row["speaker_id"] == "@player" and row["current_turn"]
        ][-1]
        dimension, level, explanation = BEATS[self.beat].feelings[actor]
        body["experiences"] = [
            {
                "channel": "affect",
                "dimension": dimension,
                "level": level,
                "about_id": "@player",
                "personal_motive_ids": ["character"],
                "explanation": explanation,
                "citations": [{"source_id": trigger["source_id"], "quote": trigger["text"]}],
                "alternatives": [],
                "unknowns": ["Oleg's current independently verified safety"],
            }
        ]
        return json.dumps(body, ensure_ascii=False)

    def review(self, supplied):
        if WRONG_LOCATION in " ".join(supplied["passages"].values()):
            self.reviews.append(supplied)
            return json.dumps(
                {
                    "matches": False,
                    "issues": [
                        "Lina's move to the bridge contradicts the supplied room and host resolution."
                    ],
                }
            )
        return super().review(supplied)

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "repair":
            return await super().simple(system, payload, model, **kwargs)
        self.repair_inputs.append(json.loads(payload))
        router = endpoint_fixtures.make_router()

        async def completion(_):
            return response(self.story + self.footer())

        router._acompletion_with_openrouter_fallback = completion
        return await router.aexecute_simple_task(system, payload, model, **kwargs)

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        body = self.story
        if self.inject_wrong_location and self.beat == 0:
            body += "\n\n" + WRONG_LOCATION
        text = body + self.footer()

        async def chunks():
            for start in range(0, len(text), self.size):
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=text[start : start + self.size]),
                            finish_reason=None,
                        )
                    ]
                )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")]
            )

        async def completion(request):
            self.narrator_requests.append(request)
            return chunks()

        router = endpoint_fixtures.make_router()
        router._acompletion_with_openrouter_fallback = completion
        return await router.stream_simple_task(*args, **kwargs)


def visible_text(events):
    return "".join(
        json.loads(event.split("data: ", 1)[1])["content"]
        for event in events
        if event.startswith("event: chunk")
    )


def assert_cues(reply, beat):
    cues = reply.to_client_dict()["portrait_state"]
    assert cues["source_hash"] == source_hash(beat.body)
    for actor, (emotion, intensity, thought) in beat.cues.items():
        assert cues["npcs"][actor] == {
            "emotion": emotion,
            "intensity": intensity,
            "thought": thought,
        }


@pytest.mark.parametrize("size,repair", [(1, False), (31, False), (7, True)])
async def test_three_turn_emotional_scene_survives_the_real_engine(
    monkeypatch, tmp_path, size, repair
):
    roles = EmotionalRoles(size, repair)
    install(monkeypatch, roles)
    report = {
        "mode": "offline-controlled-model",
        "chunk_characters": size,
        "factual_repair_injected": repair,
        "turns": [],
    }
    async with TestSessionLocal() as db:
        user, state = await seed_emotional_scene(db)
        previous = []
        for number, beat in enumerate(BEATS):
            roles.beat = number
            host, events = await play(db, user, beat.action)
            reply = await db.get(ChatMessage, load(host.state).actors["LINA"].reply_id)
            report["turns"].append(check_turn(roles, host, events, reply, beat, previous, number))
            previous.append(reply.content)
        assert len(roles.repair_inputs) == int(repair)
        if repair:
            assert WRONG_LOCATION in roles.repair_inputs[0]["narration"]
        path = tmp_path / "emotional-scene-report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"EMOTIONAL_SCENE_REPORT {path}")


def check_turn(roles, host, events, reply, beat, previous, number):
    saved = load(host.state)
    assert saved.usage.status == "validated" and not saved.usage.simplified
    assert not saved.usage.actor_failures
    assert host.state.current_scene_id == "START"
    assert reply.content == visible_text(events) == beat.body
    assert all(marker in reply.content for marker in beat.markers)
    assert "<npc-state>" not in "".join(events)
    assert_cues(reply, beat)
    context = "\n\n".join(row["content"] for row in roles.narrator_requests[-1]["messages"])
    assert all(word in context for word in ("гроза", "янтарный", "рацией"))
    assert all(text in context for text in previous)
    check_minds(saved, beat)
    projected = roles.reviews[-1]["contract"]
    for actor, (_, _, reason) in beat.feelings.items():
        assert reason in str(projected[actor]["subjective_experience_not_traits"])
    planner = format_recent_narration(
        [{"role": "assistant", "content": reply.content}], for_story_initiative=True
    )
    assert beat.body in planner
    return {
        "turn": number + 1,
        "reply": reply.content,
        "portrait_state": reply.portrait_state,
        "review_status": saved.usage.status,
        "repairs": saved.usage.repairs,
        "pass": True,
    }


def check_minds(saved, beat):
    for actor, (dimension, level, _) in beat.feelings.items():
        mind = saved.minds[actor]
        assert mind.genesis.identity.description == IDENTITIES[actor][0]
        assert any(
            state.dimension == dimension
            and state.level == level
            and state.record_id in saved.actors[actor].experience_ids
            for state in mind.snapshot.experiences
        )
