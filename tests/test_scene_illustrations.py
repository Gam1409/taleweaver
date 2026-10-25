"""VN moment images freeze visible facts and never mutate portraits or current scenes."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.api.routes import visual_jobs
from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.config import settings
from backend.engine.media_engine import MediaEngine
from backend.engine.scene_illustrations import REGISTRY_KEY, capture_scene_snapshot, render
from backend.engine.scene_illustrations.snapshots import MAX_SNAPSHOTS, registry_of
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from backend.utils.path_security import local_path_to_data_url
from tests.conftest import TestSessionLocal
from tests.test_comfyui import workflow

__all__ = ["workflow"]


@pytest_asyncio.fixture
async def illustration_world(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    visual_jobs._jobs.clear()
    async with TestSessionLocal() as db:
        user = (await db.scalars(select(User))).first()
        user.t2i_settings = {
            "advanced_model_provider": "stable_diffusion",
            "advanced_model": "scene-checkpoint",
            "scene_model_quality": "advanced",
            "advanced_steps": 23,
            "advanced_min_long_edge": 768,
        }
        template = AdventureTemplate(
            id="moment-template", title="Evening", owner_id=user.id, rule_enforcement_mode="vn"
        )
        rpg_template = AdventureTemplate(
            id="moment-rpg-template",
            title="Adventure",
            owner_id=user.id,
            rule_enforcement_mode="rpg",
        )
        avatar = Avatar(id="moment-avatar", name="Hero", user_id=user.id)
        db.add_all([template, rpg_template, avatar])
        await db.flush()
        for sid, owner, mode in [
            ("moment", user.id, "vn"),
            ("foreign", "other-owner", "vn"),
            ("rpg-moment", user.id, "rpg"),
        ]:
            mode_template = template if mode == "vn" else rpg_template
            session = GameSession(
                id=sid, user_id=owner, template_id=mode_template.id, avatar_id=avatar.id
            )
            state = SessionState(
                session_id=sid,
                template_id=mode_template.id,
                avatar_id=avatar.id,
                current_scene_id="CAFE",
                entity_states={
                    AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: {
                        "adventure": {"rule_enforcement_mode": mode},
                        "original_manifest": {},
                    },
                    "NPC": {"description": "Future blue coat", "secret": "hidden map"},
                },
            )
            db.add_all([session, state])
            await db.flush()
            message = ChatMessage(
                id=f"{sid}-reply", session_id=sid, role="assistant", content="Лина подала чашку."
            )
            db.add(message)
            await db.flush()
            await capture_scene_snapshot(
                db,
                state,
                message,
                {
                    "setting": "A quiet cafe",
                    "characters": [{"name": "Лина", "clothing": "Red coat", "secret": "secret"}],
                    "inventory": ["hidden map"],
                },
            )
        db.add_all(
            [
                WorldScene(
                    id="CAFE",
                    session_id="moment",
                    label="Cafe",
                    description="Cafe",
                    image_url="/data/background.png",
                ),
                WorldEntity(
                    id="LINA",
                    session_id="moment",
                    entity_type="NPC",
                    name="Lina",
                    current_scene_id="CAFE",
                    description="A woman",
                    image_url="/data/portrait.png",
                ),
                ChatMessage(id="old-reply", session_id="moment", role="assistant", content="Old"),
                ChatMessage(id="user-reply", session_id="moment", role="user", content="Hello"),
            ]
        )
        await db.commit()
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        target = Path(kwargs["target_dir"], kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake image")
        return local_path_to_data_url(str(target))

    async def adapt(description, rules, user, **kwargs):
        return description

    monkeypatch.setattr(render, "adapt_body", adapt)
    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    yield calls
    for job in list(visual_jobs._jobs.values()):
        if job.task and not job.task.done():
            job.task.cancel()
            await job.task
    visual_jobs._jobs.clear()


async def finish(client, session_id="moment", message_id="moment-reply"):
    job_id = str(uuid4())
    response = await client.post(
        "/api/settings/visual-jobs",
        json={
            "id": job_id,
            "operation": "session_illustration",
            "session_id": session_id,
            "payload": {"message_id": message_id},
        },
    )
    assert response.status_code == 200, response.text
    await visual_jobs._jobs[job_id].task
    return visual_jobs._jobs[job_id].public()


async def test_snapshot_not_current_state_drives_generation(auth_client, illustration_world):
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    request = illustration_world[0]
    assert "Red coat" in request["prompt"]
    assert "Future blue coat" not in request["prompt"]
    assert "hidden map" not in request["prompt"]
    assert request["provider_options"]["steps"] == 23
    assert request["provider_options"]["width"] > request["provider_options"]["height"]
    response = await auth_client.get(
        "/api/adventures/moment/illustrations", params={"message_id": "moment-reply"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["image_url"] == result["result"]["image_url"]
    assert response.json()["snapshot_source"] == "message_time"
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert state.current_scene_id == "CAFE"
        assert state.entity_states["NPC"]["description"] == "Future blue coat"
        scene = await db.scalar(select(WorldScene).where(WorldScene.session_id == "moment"))
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == "moment"))
        assert scene.image_url == "/data/background.png"
        assert npc.image_url == "/data/portrait.png"


@pytest.mark.parametrize(
    "session_id,message_id",
    [
        ("foreign", "foreign-reply"),
        ("rpg-moment", "rpg-moment-reply"),
        ("moment", "foreign-reply"),
        ("moment", "user-reply"),
        ("moment", "old-reply"),
    ],
)
async def test_invalid_targets_never_reach_provider(
    auth_client, illustration_world, session_id, message_id
):
    result = await finish(auth_client, session_id, message_id)
    assert result["state"] == "failed"
    assert illustration_world == []


async def test_old_message_explains_unavailable_snapshot(auth_client, illustration_world):
    response = await auth_client.get(
        "/api/adventures/moment/illustrations", params={"message_id": "old-reply"}
    )
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "snapshot" in response.json()["reason"]
    response = await auth_client.post(
        "/api/adventures/moment/illustrations", json={"message_id": "old-reply"}
    )
    assert response.status_code == 409
    assert illustration_world == []


@pytest.mark.parametrize("change", ["delete", "edit", "rewind"])
async def test_late_result_is_discarded_after_story_change(
    auth_client, illustration_world, monkeypatch, change
):
    original = MediaEngine.generate_image

    async def generate(**kwargs):
        async with TestSessionLocal() as db:
            if change == "delete":
                await db.execute(delete(ChatMessage).where(ChatMessage.id == "moment-reply"))
            elif change == "edit":
                message = await db.get(ChatMessage, "moment-reply")
                message.content = "Different scene"
            else:
                state = await db.scalar(
                    select(SessionState).where(SessionState.session_id == "moment")
                )
                data = deepcopy(state.entity_states)
                data[REGISTRY_KEY]["snapshots"]["moment-reply"]["nonce"] = "new-timeline"
                state.entity_states = data
            await db.commit()
        return await original(**kwargs)

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await finish(auth_client)
    assert result["state"] == "failed"
    request = illustration_world[0]
    assert not Path(request["target_dir"], request["filename"]).exists()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert registry_of(state.entity_states)["images"] == {}


async def test_concurrent_progress_is_preserved(auth_client, illustration_world, monkeypatch):
    original = MediaEngine.generate_image

    async def generate(**kwargs):
        async with TestSessionLocal() as db:
            state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
            state.current_scene_id = "PARK"
            state.entity_states = {**state.entity_states, "new_fact": {"value": 9}}
            await db.commit()
        return await original(**kwargs)

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    assert (await finish(auth_client))["state"] == "succeeded"
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert state.current_scene_id == "PARK"
        assert state.entity_states["new_fact"]["value"] == 9


async def test_snapshot_bound_preserves_generated_image_metadata(auth_client, illustration_world):
    assert (await finish(auth_client))["state"] == "succeeded"
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        for index in range(MAX_SNAPSHOTS):
            message = ChatMessage(
                id=f"next-{index}", session_id="moment", role="assistant", content=f"Next {index}"
            )
            await capture_scene_snapshot(db, state, message)
        registry = registry_of(state.entity_states)
        assert len(registry["snapshots"]) == MAX_SNAPSHOTS
        assert "moment-reply" not in registry["snapshots"]
        assert registry["images"]["moment-reply"]["image_url"]


@pytest.mark.parametrize("adapt_with_llm", [True, False])
async def test_comfy_story_preset_is_used(
    auth_client, illustration_world, workflow, monkeypatch, adapt_with_llm
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    async with TestSessionLocal() as db:
        user = (await db.scalars(select(User))).first()
        user.t2i_settings = {
            **user.t2i_settings,
            "comfyui_presets": {
                "story-art": {
                    "name": "Story",
                    "generate": workflow,
                    "prompt_rules": {
                        "adapt_with_llm": adapt_with_llm,
                        "language": "English",
                        "format": "tags",
                        "prefix": "model-quality-token",
                        "suffix": "model-style-token",
                        "instructions": "Use visual tags for this checkpoint.",
                    },
                }
            },
            "comfyui_url": "http://127.0.0.1:8188",
        }
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        state.selected_image_styles = [{"instruction": "Soft watercolor with ink outlines"}]
        data = deepcopy(state.entity_states)
        data[AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY]["original_manifest"] = {
            "visual_presets": {"advanced": "story-art"}
        }
        state.entity_states = data
        await db.commit()

    adaptations = []

    async def adapt(description, rules, user, **kwargs):
        adaptations.append(rules)
        assert "Soft watercolor with ink outlines" in description
        return "2 adults, standing apart, woman beside window, man seated"

    monkeypatch.setattr(render, "adapt_body", adapt)
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert illustration_world[0]["provider"] == "comfyui"
    options = illustration_world[0]["provider_options"]
    assert options["comfyui_assignments"]["advanced"] == "story-art"
    assert options["_prompt_prepared"] is True
    assert len(adaptations) == 1
    assert adaptations[0].format == ("tags" if adapt_with_llm else "description")
    if adapt_with_llm:
        assert "Use visual tags for this checkpoint." in adaptations[0].instructions
    assert "final visible moment" in adaptations[0].instructions
    assert "later departure" in adaptations[0].instructions

    from backend.engine import image_prompt_adapter

    async def unexpected_adaptation(*args, **kwargs):
        raise AssertionError("The image provider must not reinterpret the final frame")

    monkeypatch.setattr(image_prompt_adapter, "adapt_body", unexpected_adaptation)
    prepared = await image_prompt_adapter.prepare_prompt(illustration_world[0]["prompt"], options)
    assert prepared["positive"] == (
        "model-quality-token, 2 adults, standing apart, woman beside window, man seated, "
        "model-style-token"
    )


async def test_timeout_keeps_previous_image(auth_client, illustration_world, monkeypatch):
    original = await finish(auth_client)

    async def timeout(**kwargs):
        raise TimeoutError

    monkeypatch.setattr(MediaEngine, "generate_image", timeout)
    result = await finish(auth_client)
    assert result["state"] == "failed"
    assert "timed out" in result["message"]
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert (
            registry_of(state.entity_states)["images"]["moment-reply"]["image_url"]
            == (original["result"]["image_url"])
        )


async def test_utility_distills_prompt_before_non_comfy_provider(
    auth_client, illustration_world, monkeypatch
):
    calls = []

    async def adapt(description, rules, user):
        calls.append((description, rules))
        return "A woman in a red coat offers a cup at a cafe."

    monkeypatch.setattr(render, "adapt_body", adapt)
    assert (await finish(auth_client))["state"] == "succeeded"
    assert len(calls) == 1
    assert calls[0][1].language == "English"
    assert "Лина" in calls[0][0]
    assert illustration_world[0]["prompt"] == "A woman in a red coat offers a cup at a cafe."


async def test_utility_failure_does_not_submit_an_image(
    auth_client, illustration_world, monkeypatch
):
    async def timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(render, "adapt_body", timeout)
    assert (await finish(auth_client))["state"] == "failed"
    assert illustration_world == []


async def test_capture_merges_images_finished_during_turn(auth_client, illustration_world):
    async with TestSessionLocal() as turn_db:
        state = await turn_db.scalar(
            select(SessionState).where(SessionState.session_id == "moment")
        )
        stale = deepcopy(state.entity_states)
        result = await finish(auth_client)
        assert result["state"] == "succeeded"
        state.entity_states = {**stale, "turn_fact": {"value": 7}}
        message = ChatMessage(
            id="after-generation", session_id="moment", role="assistant", content="A new moment"
        )
        turn_db.add(message)
        await turn_db.flush([message])
        await capture_scene_snapshot(turn_db, state, message)
        await turn_db.commit()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert (
            registry_of(state.entity_states)["images"]["moment-reply"]["image_url"]
            == (result["result"]["image_url"])
        )
        assert state.entity_states["turn_fact"]["value"] == 7


async def test_completed_moment_freezes_public_positions_without_private_items(
    auth_client, illustration_world
):
    from backend.engine.visual_novel.runtime import capture_completed_moment

    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == "moment"))
        npc.spatial_position = "beside the window, apart from the seated hero"
        npc.goal = "Private goal"
        avatar = await db.get(Avatar, "moment-avatar")
        avatar.inventory = [
            {"id": "COAT", "name": "Red coat", "description": "Wool coat"},
            {"id": "LETTER", "name": "Hidden letter", "description": "Private secret"},
        ]
        avatar.equipment = {"body": "COAT"}
        await db.flush()
        message = ChatMessage(
            id="final-moment",
            session_id="moment",
            role="assistant",
            content="<short pause> Лина отошла к окну, отпустив руку героя.",
        )
        db.add(message)
        assert message.scene_id is None
        await capture_completed_moment(SimpleNamespace(db=db, state=state, avatar=avatar), message)
        snapshot = registry_of(state.entity_states)["snapshots"][message.id]
        facts = snapshot["visible_facts"]
        assert facts["setting"] == "Cafe"
        assert message.scene_id == "CAFE"
        assert facts["characters"][1]["position"] == npc.spatial_position
        assert "Red coat" in facts["characters"][0]["clothing"]
        assert "Hidden letter" not in str(facts)
        assert "Private goal" not in str(facts)
        assert snapshot["narration"] == message.content
        assert "<short pause>" in message.content
