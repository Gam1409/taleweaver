"""Short place references reuse semantic matches without bypassing routes or inventing clones."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.dynamic_locations.identity import clarification_block, place_catalog
from backend.engine.dynamic_locations.prompts import intent_schema
from backend.engine.dynamic_locations.schema import PlaceProposal, registry
from backend.engine.dynamic_locations.service import materialize, resolve_proposal
from backend.engine.llm_intents import ChatProgressionIntent
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_dynamic_locations import decision, setup
from tests.test_game_loop import _llm_call_text

ACTION = "Мы зашли в лабораторию."


async def hospital(db, *, locked=False):
    manager, _ = await setup(db, "building")
    db.add_all(
        [
            WorldScene(
                session_id=manager.game_id,
                id="CLINICAL_LAB",
                label="Клиническая лаборатория",
                description="Здесь проводят клинические исследования и анализируют образцы.",
            ),
            WorldExit(
                session_id=manager.game_id,
                from_scene_id="START",
                to_scene_id="CLINICAL_LAB",
                label="Коридор к анализам",
                is_locked=locked,
            ),
        ]
    )
    await db.flush()
    return manager


async def apply(manager, result, *, complete=True):
    scenes = list(
        (
            await manager.db.scalars(
                select(WorldScene).where(WorldScene.session_id == manager.game_id)
            )
        ).all()
    )
    exits = list(
        (
            await manager.db.scalars(
                select(WorldExit).where(WorldExit.session_id == manager.game_id)
            )
        ).all()
    )
    return await materialize(
        manager,
        PlaceProposal(label="лаборатория", action_quote=ACTION),
        result,
        ACTION,
        "Нужно сделать клинический анализ образца.",
        scenes,
        exits,
        catalog_complete=complete,
    )


def match(score, **changes):
    return decision(
        action_quote=ACTION,
        label="лаборатория",
        description="Помещение для анализов",
        identity_resolution="existing",
        scene_matches=[{"scene_id": "CLINICAL_LAB", "score": score}],
        **changes,
    )


@pytest.mark.parametrize(
    "score, expected", [(0.69, None), (0.70, "CLINICAL_LAB"), (0.95, "CLINICAL_LAB")]
)
@pytest.mark.asyncio
async def test_contextual_match_uses_canonical_scene_at_seventy_percent(score, expected):
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        assert await apply(manager, match(score, local_to_current_scene=False)) == expected
        assert not registry(manager.state).get("places")
        assert not getattr(manager, "_dynamic_scene_images", [])


@pytest.mark.asyncio
async def test_known_locked_lab_never_becomes_an_unlocked_duplicate():
    async with TestSessionLocal() as db:
        manager = await hospital(db, locked=True)
        assert await apply(manager, match(0.99)) is None
        assert not registry(manager.state).get("places")


@pytest.mark.asyncio
async def test_unscored_short_name_cannot_clone_a_nearby_existing_place():
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        result = decision(action_quote=ACTION, label="лаборатория")
        assert await apply(manager, result) is None
        assert clarification_block(manager)
        assert not registry(manager.state).get("places")


@pytest.mark.asyncio
async def test_different_context_can_still_create_a_distinct_place_with_a_similar_label():
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        result = decision(
            action_quote=ACTION,
            label="лаборатория",
            scene_matches=[{"scene_id": "CLINICAL_LAB", "score": 0.20}],
        )
        destination = await apply(manager, result)
        assert destination.startswith("dyn_")


@pytest.mark.asyncio
async def test_context_can_distinguish_a_second_lab_with_similar_name():
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        db.add(
            WorldScene(
                session_id=manager.game_id,
                id="RESEARCH_LAB",
                label="Исследовательская лаборатория",
                description="Экспериментальная физика и измерительные приборы.",
            )
        )
        await db.flush()
        result = match(0.90)
        result.scene_matches.append(
            type(result.scene_matches[0])(scene_id="RESEARCH_LAB", score=0.35)
        )
        assert await apply(manager, result) == "CLINICAL_LAB"


@pytest.mark.asyncio
async def test_ambiguity_stays_in_place_and_requests_an_in_character_question():
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        db.add_all(
            [
                WorldScene(
                    session_id=manager.game_id,
                    id="RESEARCH_LAB",
                    label="Исследовательская лаборатория",
                    description="Другая лаборатория.",
                ),
                WorldExit(
                    session_id=manager.game_id,
                    from_scene_id="START",
                    to_scene_id="RESEARCH_LAB",
                    label="Другой коридор",
                    is_locked=False,
                ),
            ]
        )
        await db.flush()
        result = match(0.85)
        result.identity_resolution = "ambiguous"
        result.scene_matches.append(
            type(result.scene_matches[0])(scene_id="RESEARCH_LAB", score=0.85)
        )
        assert await apply(manager, result) is None
        assert not registry(manager.state).get("places")
        prompt = clarification_block(manager)
        assert "one brief clarification in the RP" in prompt
        assert "Клиническая лаборатория" in prompt
        assert "Исследовательская лаборатория" in prompt
        assert "CLINICAL_LAB" not in prompt
        assert "0.85" not in prompt
        await resolve_proposal(manager, ChatProgressionIntent(), "Пока подождём.", [], "Russian")
        assert clarification_block(manager) == ""


@pytest.mark.asyncio
async def test_unknown_id_and_unreviewed_maps_never_create_or_teleport():
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        result = match(0.95)
        result.scene_matches[0].scene_id = "NONEXISTENT"
        assert await apply(manager, result) is None
        result = decision(action_quote=ACTION, label="New laboratory")
        assert await apply(manager, result, complete=False) is None
        assert not registry(manager.state).get("places")


def test_catalog_is_bounded_and_prioritizes_neighbors_with_descriptions():
    scenes = [
        SimpleNamespace(id=f"ROOM_{i}", label=f"Room {i}", description="Purpose " * 100)
        for i in range(100)
    ]
    exits = [SimpleNamespace(from_scene_id="ROOM_0", to_scene_id="ROOM_99")]
    catalog = place_catalog(scenes, exits, "ROOM_0", {})
    assert catalog["complete"] is False
    assert len(catalog["places"]) == 80
    assert catalog["places"][1]["id"] == "ROOM_99"
    assert sum(len(p["description"]) for p in catalog["places"]) <= 6000


@pytest.mark.asyncio
async def test_existing_confirmation_gets_semantic_context_without_an_extra_llm_call(monkeypatch):
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        confirmation = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(return_value=match(0.92))
        )
        monkeypatch.setattr(
            "backend.engine.dynamic_locations.service.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: confirmation),
        )
        intent = SimpleNamespace(
            new_local_place=PlaceProposal(label="лаборатория", action_quote=ACTION),
            new_scene_id=None,
        )
        await resolve_proposal(
            manager,
            intent,
            ACTION,
            [{"role": "assistant", "content": "Образцы нужно отнести на клинический анализ."}],
            "Russian",
        )
        assert intent.new_scene_id == "CLINICAL_LAB"
        assert confirmation.aexecute_complex_task.await_count == 1
        args = confirmation.aexecute_complex_task.call_args.kwargs
        context = json.loads(args["user_prompt"])
        clinic = next(
            p for p in context["existing_place_catalog"]["places"] if p["id"] == "CLINICAL_LAB"
        )
        assert "образцы" in clinic["description"]
        assert "0.70" in args["system_prompt"]


def test_nonfinite_scores_are_rejected():
    with pytest.raises(ValidationError):
        match(float("nan"))


@pytest.mark.asyncio
async def test_ambiguous_turn_passes_rp_question_to_narrator_and_keeps_the_current_scene(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        manager = await hospital(db)
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=intent_schema(ChatProgressionIntent, manager.state)(
                new_local_place=PlaceProposal(label="лаборатория", action_quote=ACTION)
            )
        )

        async def stream(*args, **kwargs):
            yield MagicMock(
                choices=[
                    MagicMock(delta=MagicMock(content="В какую лабораторию вы направляетесь?"))
                ]
            )

        llm.stream_simple_task = AsyncMock(return_value=stream())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        result = match(0.90)
        result.identity_resolution = "ambiguous"
        confirmation = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(return_value=result)
        )
        monkeypatch.setattr(
            "backend.engine.dynamic_locations.service.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: confirmation),
        )
        chunks = [
            chunk
            async for chunk in GameTurnManager(db, manager.game_id, manager.user).process_turn(
                ACTION
            )
        ]
        await db.refresh(manager.state)
        assert manager.state.current_scene_id == "START"
        assert not registry(manager.state).get("places")
        prompt = _llm_call_text(llm.stream_simple_task.await_args_list[0])
        assert "DESTINATION NEEDS CLARIFICATION" in prompt
        assert "not permission to continue" in prompt
        assert "event: error" not in "".join(chunks)
