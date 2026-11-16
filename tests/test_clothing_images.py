"""Image requests preserve frozen wardrobe facts and provider contracts."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.llm_router import GameMasterLLM
from backend.engine.clothing.frames import extract_frame
from backend.engine.clothing.visuals import canonical_inventory, character_visuals
from backend.engine.media_engine import MediaEngine
from backend.engine.scene_illustrations import capture_scene_snapshot, render
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_illustrations.source_quality import build_prompt
from backend.engine.scene_illustrations.visual_context import VisualContext
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_scene_illustrations import finish, illustration_world
from tests.test_session_portraits import finish_job, portrait_world, start_job

__all__ = ["illustration_world", "portrait_world"]
HIDDEN = "HIDDEN_VIOLET_UNDERSHIRT"
PROFILE = {
    "version": 1,
    "appearance": {"age_years": 30, "hair": "short dark hair"},
    "worn": [{"item_id": "INNER"}, {"item_id": "COAT"}],
}
ITEMS = [
    {
        "id": "INNER",
        "name": HIDDEN,
        "clothing": {"layer": 1, "coverage": ["torso", "arms"], "opaque": True},
    },
    {
        "id": "COAT",
        "name": "Red coat",
        "clothing": {"layer": 2, "coverage": ["torso", "arms"], "opaque": True},
    },
]


def frame_model(monkeypatch, *, character_id="LINA", result=None):
    result = result or {"figures": [{"character_id": character_id, "action": "withdrawing"}]}
    llm = SimpleNamespace(model="small", aexecute_complex_task=AsyncMock(return_value=result))
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *args: llm)
    return llm


async def managed_snapshot():
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        message = await db.get(ChatMessage, "moment-reply")
        message.content = f"Lina wears {HIDDEN} under her coat, then steps back."
        facts = character_visuals({"id": "LINA", "name": "Lina", "visual_profile": PROFILE}, ITEMS)
        await capture_scene_snapshot(db, state, message, {"setting": "Cafe", "characters": [facts]})
        await db.commit()


async def test_moment_uses_frozen_public_clothing_and_source_in_one_adaptation(
    auth_client, illustration_world, monkeypatch
):
    llm = frame_model(monkeypatch)
    adapted = []

    async def adapt(description, rules, user, **kwargs):
        adapted.append(description)
        return "Lina in a Red coat, withdrawing from the window."

    monkeypatch.setattr(render, "adapt_body", adapt)
    await managed_snapshot()
    # Later current state must not replace the frozen outfit.
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == "moment"))
        npc.visual_profile = {"version": 1, "appearance": {"hair": "FUTURE_HAIR"}, "worn": []}
        await db.commit()
    assert (await finish(auth_client))["state"] == "succeeded"
    request = illustration_world[0]
    llm.aexecute_complex_task.assert_not_awaited()
    assert len(adapted) == 1
    # Story text remains available to the adapter, but private wardrobe state is not added.
    assert HIDDEN in adapted[0]
    assert "Red coat" in adapted[0]
    source_data = json.loads(adapted[0].split("\nSCENE DATA:\n", 1)[1])
    assert HIDDEN not in str(source_data["message_time_state"])
    assert HIDDEN not in str(request)
    assert "FUTURE_HAIR" not in request["prompt"]
    assert "Red coat" in request["prompt"]
    assert "withdrawing" in request["prompt"]
    assert "_managed_frame_source" not in request["provider_options"]
    assert request["provider_options"]["_prompt_prepared"] is True


async def test_managed_portrait_does_not_use_description_or_journal(
    auth_client, portrait_world, monkeypatch
):
    llm = frame_model(monkeypatch, character_id="NPC_NEW")
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.visual_profile = deepcopy(PROFILE)
        npc.inventory = deepcopy(ITEMS)
        npc.description = HIDDEN
        await db.commit()
    job = await start_job(
        auth_client,
        payload={"target_id": "NPC_NEW", "change_description": f"Smile, wearing {HIDDEN}."},
    )
    result = await finish_job(auth_client, job)
    assert result["state"] == "succeeded", result
    request = portrait_world[0]
    assert "Red coat" in request["prompt"]
    assert "short dark hair" in request["prompt"]
    assert HIDDEN not in str(request)
    assert "Scarred sailor" not in request["prompt"]
    assert llm.aexecute_complex_task.await_count == 1


async def test_completed_moment_projects_and_freezes_managed_clothing(
    auth_client, illustration_world
):
    from backend.engine.visual_novel.runtime import capture_completed_moment

    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        avatar = await db.get(Avatar, "moment-avatar")
        avatar.visual_profile = deepcopy(PROFILE)
        avatar.inventory = deepcopy(ITEMS)
        avatar.description = HIDDEN
        message = ChatMessage(
            id="managed-clothes", session_id="moment", role="assistant", content=HIDDEN
        )
        db.add(message)
        await capture_completed_moment(SimpleNamespace(db=db, state=state, avatar=avatar), message)
        frozen = registry_of(state.entity_states)["snapshots"][message.id]
        assert frozen["narration"] == HIDDEN
        assert HIDDEN not in str(frozen["visible_facts"])
        assert "Red coat" in str(frozen["visible_facts"])
        assert frozen["visible_facts"]["characters"][0]["managed_clothing"] is True
        avatar.visual_profile = {"version": 1, "appearance": {}, "worn": []}
        assert "Red coat" in str(frozen["visible_facts"])


async def test_frame_rejects_free_text_and_unknown_cast(monkeypatch):
    llm = frame_model(monkeypatch, result={"figures": [{"character_id": "LINA", "action": HIDDEN}]})
    with pytest.raises(ValueError):
        await extract_frame(object(), HIDDEN, [{"id": "LINA"}])
    llm.aexecute_complex_task.return_value = {"figures": [{"character_id": "UNKNOWN"}]}
    with pytest.raises(ValueError, match="unknown"):
        await extract_frame(object(), HIDDEN, [{"id": "LINA"}])


async def test_source_adapter_failure_never_submits_image(
    auth_client, illustration_world, monkeypatch
):
    monkeypatch.setattr(render, "adapt_body", AsyncMock(side_effect=TimeoutError("test timeout")))
    await managed_snapshot()
    assert (await finish(auth_client))["state"] == "failed"
    assert illustration_world == []


async def test_preparation_adapts_source_once(monkeypatch):
    adapt = AsyncMock(return_value="safe")
    monkeypatch.setattr(render, "adapt_body", adapt)
    request = {
        "prompt": "Complete scene and frozen state",
        "provider": "stable_diffusion",
        "provider_options": {"_prompt_user": object()},
    }
    await render.prepare_moment_prompt(request)
    assert request["prompt"] == "safe"
    adapt.assert_awaited_once()
    assert adapt.call_args.args[0] == "Complete scene and frozen state"
    assert request["provider_options"]["_prompt_prepared"] is True


def test_invalid_managed_profile_does_not_fall_back_to_description():
    facts = character_visuals(
        {"id": "A", "name": "A", "visual_profile": {"version": 99}, "description": HIDDEN}, []
    )
    assert facts["managed_clothing"] is True
    assert HIDDEN not in str(facts)
    empty = character_visuals({"id": "A", "visual_profile": {}, "description": HIDDEN}, [])
    assert empty["managed_clothing"] is True
    assert "do not infer undress" in empty["clothing"]


def test_database_garments_resolve_metadata_without_null_top_level_shadowing():
    entities = [
        SimpleNamespace(
            id=item["id"],
            name=item["name"],
            description=HIDDEN,
            metadata_json={"clothing": item["clothing"]},
        )
        for item in ITEMS
    ]
    owned = canonical_inventory(["INNER", "COAT"], entities)
    facts = character_visuals({"id": "A", "visual_profile": PROFILE}, owned)
    assert "Red coat" in facts["clothing"]
    assert HIDDEN not in str(facts)


def test_unknown_owned_outer_garment_prevents_inner_layer_disclosure():
    owned = canonical_inventory(["INNER", "COAT"], [ITEMS[0]])
    facts = character_visuals({"id": "A", "visual_profile": PROFILE}, owned)
    assert facts["clothing_detail_limited"] is True
    assert HIDDEN not in str(facts)
    assert "do not infer undress" in facts["clothing"]


async def test_managed_comfy_prompt_keeps_style_policy_and_tokens_once(monkeypatch):
    from backend.engine import image_prompt_adapter

    rules = ImagePromptRules(format="tags", prefix="PREFIX", suffix="SUFFIX", instructions="Policy")
    calls = []

    async def adapt(description, policy, user, **kwargs):
        calls.append((description, policy, kwargs))
        return "safe visible coat"

    monkeypatch.setattr(render, "adapt_body", adapt)
    monkeypatch.setattr(render, "prompt_rules", lambda _: rules)
    monkeypatch.setattr(render, "select_profile", lambda _: SimpleNamespace(mature_themes=True))
    monkeypatch.setattr(image_prompt_adapter, "prompt_rules", lambda _: rules)
    monkeypatch.setattr(image_prompt_adapter, "negative_prompt", lambda *args: "NEGATIVE")
    character = character_visuals({"id": "LINA", "name": "Lina", "visual_profile": PROFILE}, ITEMS)
    context = VisualContext("Lina steps back.", {"characters": [character]}, "")
    request = {
        "prompt": build_prompt(context, "STYLE_ONCE"),
        "provider": "comfyui",
        "style_instruction": "STYLE_ONCE",
        "provider_options": {"_prompt_user": object()},
    }
    await render.prepare_moment_prompt(request)
    prepared = await image_prompt_adapter.prepare_prompt(
        request["prompt"], request["provider_options"]
    )
    assert len(calls) == 1
    source, policy, kwargs = calls[0]
    assert HIDDEN not in source
    assert source.count("STYLE_ONCE") == 1
    assert policy.format == "tags"
    assert "Policy" in policy.instructions
    assert kwargs == {"mature_themes": True, "nsfw_enabled": False, "nsfw_level": "hard"}
    assert prepared["positive"] == "PREFIX, safe visible coat, SUFFIX"


@pytest.mark.parametrize("kind", ["avatar", "npc"])
async def test_initial_portrait_uses_manifest_items_before_inventory_hydration(monkeypatch, kind):
    from backend.engine.manifest_apply import avatar, npcs

    module = avatar if kind == "avatar" else npcs
    ctx = SimpleNamespace(
        template_id="story",
        manifest={"objects": deepcopy(ITEMS), "plot": HIDDEN},
        style_instruction="Watercolor",
    )
    actor = {
        "id": "LINA",
        "name": "Lina",
        "description": HIDDEN,
        "role": HIDDEN,
        "visual_profile": PROFILE,
    }
    generate = AsyncMock(return_value="/data/portrait.png")

    async def run(_ctx, **kwargs):
        assert HIDDEN not in kwargs["prompt"]
        return await kwargs["factory"]()

    monkeypatch.setattr(module, "generate_image", run)
    monkeypatch.setattr(module, "t2i_config", lambda ctx: ({"t2i_settings": {}}, {}))
    monkeypatch.setattr(module, "uses_advanced_model", lambda *args: True)
    monkeypatch.setattr(MediaEngine, "generate_entity_image", generate)
    if kind == "avatar":
        await module._generate_portrait(ctx, SimpleNamespace(**actor, inventory=[], equipment={}))
    else:
        await module._generate_portrait(ctx, actor, 1, 1)
    prompt = generate.call_args.args[0]
    assert "Red coat" in prompt
    assert HIDDEN not in prompt
    assert generate.call_args.kwargs["style_instruction"] == "Watercolor"
