"""A rejected local approach cannot be recovered as prose-only visual success."""

import json

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import load
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_additional_actions_turn import observe
from tests.test_npc_two_phase_turn import PLAYER, CupRoles, reload, seed

TABLE = "FIXED_TABLE"
SPEECH = "Лина: «Я рассмотрю узор отсюда.»"
APPROACHED = "Она обошла стол и встала с другой стороны, не торопясь."
UNCHANGED = "Лина остаётся на прежнем месте и рассматривает узор издали."


class ApproachRoles(CupRoles):
    def __init__(self, *, permitted, corrected=True, classified=True):
        super().__init__([{"tool": "approach", "target_id": TABLE, "mode": "walk"}])
        self.permitted, self.corrected, self.classified = permitted, corrected, classified
        self.repairs, self.extractions = [], []

    @property
    def story(self):
        return f"{SPEECH}\n{APPROACHED}"

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair":
            self.repairs.append(json.loads(payload))
            revised = f"{SPEECH}\n{UNCHANGED if self.corrected else APPROACHED}"
            return revised if self.corrected else f"{revised}\nЗа окном пробил час."
        return await super().simple(system, payload, model, **kwargs)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        payload = json.loads(args[1])
        self.extractions.append(payload)
        passages = payload["completed_narration"]
        approached = APPROACHED in passages.values()
        key = next(
            key
            for key, text in passages.items()
            if text == (APPROACHED if approached else UNCHANGED)
        )
        frame = {
            "actor_ids": ["LINA"],
            "detail": "Лина стоит с другой стороны стола."
            if approached
            else "Лина рассматривает узор издали.",
            "evidence": key,
        }
        if self.classified or not approached:
            frame["poses"] = (
                [
                    {
                        "actor_id": "LINA",
                        "basis": "completed",
                        "posture": "standing",
                        "placement": {
                            "relation": "near",
                            "target_kind": "scene_object",
                            "target": TABLE,
                        },
                    }
                ]
                if approached
                else []
            )
        # R4 supplied only a final frame, without nominal staging changes.
        return extraction(schema, final_frame_actions=[frame])


async def prepare(db, protocol, *, enabled):
    user, state = await seed(db, protocol, pair=False)
    db.add(
        WorldEntity(
            id=TABLE,
            session_id=state.session_id,
            entity_type="OBJECT",
            name="стол",
            description="An established fixed table.",
            current_scene_id="START",
            is_portable=False,
        )
    )
    write_settings(state, VnSettings(scene_staging=enabled))
    state.entity_states = apply_command(
        state.entity_states,
        scene_id="START",
        cast=[{"id": "LINA", "name": "Лина"}],
        actor_id="LINA",
        enabled=True,
        posture="standing",
        proof=CommandProof(
            command_id="initial-standing",
            actor_id="LINA",
            scene_id="START",
            input_id="prior-input",
            request_hash="a" * 64,
            operation="set_pose",
        ),
    )
    await db.commit()
    return user, state


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("permitted", [False, True])
async def test_approach_and_frozen_visuals_follow_the_actual_owner_outcome(
    monkeypatch, protocol, permitted
):
    roles = ApproachRoles(permitted=permitted)
    install(monkeypatch, roles)
    _, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, protocol, enabled=permitted)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert any(row.startswith("event: final") for row in events), "".join(events)
        assert not any(row.startswith("event: error") for row in events)
        assert len(roles.repairs) == int(not permitted)
        accepted = APPROACHED if permitted else UNCHANGED
        chunks = [
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        ]
        assert chunks == [f"{SPEECH}\n{accepted}"]
        outcomes = publications[0].action_outcomes["LINA"]
        assert [row["status"] for row in outcomes] == (["applied"] if permitted else [])

    async with TestSessionLocal() as db:
        _, manager, _ = await reload(db, session_id, user_id)
        messages = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(SPEECH),
                )
            )
        )
        assert [message.content for message in messages] == chunks
        registry = registry_of(manager.state.entity_states)["snapshots"]
        snapshot = registry[messages[0].id]
        assert snapshot["narration"] == messages[0].content
        visible = snapshot["visible_facts"]
        position = manager.state.entity_states[STAGING_KEY]["actors"]["LINA"]
        if permitted:
            assert position["placement"]["target_id"] == TABLE
            assert position["placement"]["source_kind"] == "command"
        else:
            assert "placement" not in position
            assert APPROACHED not in json.dumps(visible, ensure_ascii=False)
        assert load(manager.state).actors["LINA"].last_publication is not None


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_r4_unclassified_frame_after_rejected_approach_cannot_publish(monkeypatch, protocol):
    roles = ApproachRoles(permitted=False, classified=False)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await prepare(db, protocol, enabled=False)

        _, events = await run(db, user, PLAYER)

        assert len(roles.repairs) == 1
        assert any(row.startswith("event: final") for row in events), "".join(events)
        chunks = [
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        ]
        assert chunks == [f"{SPEECH}\n{UNCHANGED}"]


class PoseRoles(ApproachRoles):
    def __init__(self, *, steps, text, poses, nominal=False, omit_retry=False):
        super().__init__(permitted=True, corrected=not omit_retry)
        self.steps, self.text, self.poses = steps, text, poses
        self.nominal, self.omit_retry = nominal, omit_retry

    @property
    def story(self):
        return f"{SPEECH}\n{self.text}"

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair" and self.omit_retry:
            self.repairs.append(json.loads(payload))
            return f"{self.story}\nЗа окном пробил час."
        return await super().simple(system, payload, model, **kwargs)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        payload = json.loads(args[1])
        self.extractions.append(payload)
        passages = payload["completed_narration"]
        if self.repairs and not self.omit_retry:
            text, poses = UNCHANGED, []
        else:
            text, poses = self.text, self.poses
        key = next(key for key, value in passages.items() if text in value)
        frames = (
            []
            if self.omit_retry and self.repairs
            else [
                {
                    "actor_ids": ["LINA"],
                    "detail": text,
                    "evidence": key,
                    "poses": poses,
                }
            ]
        )
        staging = (
            {
                "changes": [
                    {
                        "entity_id": "LINA",
                        "posture": "sitting",
                        "evidence": key,
                    }
                ],
                "props": [],
                "explicit": [],
            }
            if self.nominal and not self.repairs
            else None
        )
        return extraction(
            schema, final_frame_actions=frames, **({"staging": staging} if staging else {})
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("classification", ["invented", "current", "gesture", "sit"])
async def test_speech_only_and_explicit_pose_keep_independent_expression_and_current_owner(
    monkeypatch, protocol, classification
):
    poses = {
        "invented": [{"actor_id": "LINA", "basis": "completed", "posture": "sitting"}],
        "current": [{"actor_id": "LINA", "basis": "current", "posture": "standing"}],
        "gesture": [],
        "sit": [{"actor_id": "LINA", "basis": "completed", "posture": "sitting"}],
    }[classification]
    text = {
        "invented": "Лина присела рядом со столом.",
        "current": "Лина по-прежнему стоит и смотрит на узор.",
        "gesture": "Лина улыбается и чуть наклоняет голову.",
        "sit": "Лина садится, не занимая никакого стула.",
    }[classification]
    roles = PoseRoles(
        steps=[{"tool": "set_pose", "posture": "sitting"}] if classification == "sit" else [],
        text=text,
        poses=poses,
    )
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, protocol, enabled=True)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert any(row.startswith("event: final") for row in events), "".join(events)
        assert len(roles.repairs) == int(classification == "invented")
        assert len(roles.extractions) == 1 + len(roles.repairs)
    async with TestSessionLocal() as db:
        _, manager, _ = await reload(db, session_id, user_id)
        owner = manager.state.entity_states[STAGING_KEY]["actors"]["LINA"]
        assert owner["posture"]["value"] == ("sitting" if classification == "sit" else "standing")
        assert "placement" not in owner
        snapshots = registry_of(manager.state.entity_states)["snapshots"]
        assert len(snapshots) == 1
        final = next(iter(snapshots.values()))
        assert (UNCHANGED if classification == "invented" else text) in final["narration"]


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("omit_retry", [False, True])
async def test_repeated_or_hidden_rejected_approach_rolls_back_before_any_chunk(
    monkeypatch, protocol, omit_retry
):
    if omit_retry:
        roles = PoseRoles(
            steps=[],
            text=APPROACHED,
            poses=[
                {
                    "actor_id": "LINA",
                    "basis": "completed",
                    "placement": {
                        "relation": "near",
                        "target_kind": "scene_object",
                        "target": TABLE,
                    },
                }
            ],
            omit_retry=True,
        )
    else:
        roles = ApproachRoles(permitted=False, corrected=False)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, protocol, enabled=omit_retry)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert len(roles.repairs) == 1
        assert len(roles.extractions) == 2
        assert any(row.startswith("event: error") for row in events), "".join(events)
        assert not any(row.startswith(("event: chunk", "event: final")) for row in events)
    async with TestSessionLocal() as db:
        _, manager, _ = await reload(db, session_id, user_id)
        assert "placement" not in manager.state.entity_states[STAGING_KEY]["actors"]["LINA"]
        assert not registry_of(manager.state.entity_states)["snapshots"]
        messages = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(APPROACHED),
                )
            )
        )
        assert messages == []
