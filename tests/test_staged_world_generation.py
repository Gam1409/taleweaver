"""Interrupted world creation resumes validated stages without regenerating canon."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.staged_world.checkpoints import Checkpoints, input_fingerprint
from backend.engine.staged_world.pipeline import StagedGeneration
from backend.engine.staged_world.prompts import detail_context
from backend.models.adventure_template import AdventureTemplate


def seed(identifier, name, scene="", owner=""):
    return dict(
        id=identifier, name=name, summary="Known facts", start_scene_id=scene, owner_id=owner
    )


@pytest.fixture
def plan():
    return {
        "foundation": dict(
            teaser="A meeting", language="Russian", origin_id="", plot="Reunion", rules="No magic"
        ),
        "protagonist": seed("PROTAGONIST", "Иван"),
        "scenes": [seed("CITY", "Город"), seed("TAVERN", "Таверна")],
        "exits": [dict(from_scene_id="CITY", to_scene_id="TAVERN", label="Дверь", is_locked=False)],
        "npcs": [seed("LENA", "Лена", "TAVERN")],
        "objects": [{**seed("LETTER", "Письмо", "TAVERN", "LENA"), "item_type": "PICKABLE"}],
        "sequences": [],
        "quests": [],
        "awards": [],
        "scripts": [],
    }


def details(kind, rows):
    if kind == "protagonist":
        return {
            "protagonist": dict(
                name=rows[0]["name"],
                role="Visitor",
                description="An old friend",
                goal="Meet Lena",
                character="Thoughtful",
                strength=10,
                dexterity=10,
                intelligence=10,
                wisdom=10,
                charisma=10,
                armor_class=10,
                hp=100,
                mana=0,
                stamina=100,
                starting_equipment={},
            )
        }
    result = []
    for row in rows:
        entry = dict(id=row["id"], name=row["name"], description="A detail")
        if kind in {"npcs", "objects"}:
            entry.update(
                start_scene_id=row["start_scene_id"],
                spatial_position="Near the door",
                is_hidden=False,
            )
        if kind == "npcs":
            entry.update(
                goal="Talk",
                character="Reserved",
                npc_type="HUMANOID",
                hp=100,
                mana=0,
                stamina=100,
                is_attackable=False,
                is_killable=False,
            )
        if kind == "objects":
            entry.update(item_type="PICKABLE", is_portable=True)
        result.append(entry)
    return {"items": result}


class FakeLLM:
    def __init__(self, plan, fail=None, bad_id=False):
        self.plan = plan
        self.fail = fail
        self.bad_id = bad_id
        self.calls = []
        self.max_tokens = 8192
        self.model = "test-generator"

    async def aexecute_complex_task(self, **kwargs):
        key = kwargs["phase"]
        self.calls.append(kwargs)
        if key == self.fail:
            raise TimeoutError("Interrupted server response")
        if key == "plan":
            result = deepcopy(self.plan)
        else:
            kind, _, offset = key.partition(":")
            rows = (
                [self.plan[kind]]
                if kind == "protagonist"
                else self.plan[kind][int(offset) : int(offset) + 2]
            )
            result = details(kind, rows)
            if self.bad_id and kind == "objects":
                result["items"][0]["id"] = "UNPLANNED_ITEM"
        return kwargs["response_model"].model_validate(result)


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr("backend.engine.generation_control.assert_generation_current", AsyncMock())
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    db.no_autoflush = nullcontext()
    adventure = AdventureTemplate(id="world", title="Story", generation_checkpoint=None)
    return db, adventure


def runner(llm, storage, prompt="Russian story", mode="vn"):
    db, adventure = storage
    store = Checkpoints(db, adventure, input_fingerprint("system", prompt, {}, mode))
    return StagedGeneration(
        llm=llm,
        store=store,
        system="system",
        user=prompt,
        metadata={},
        mode=mode,
        status=AsyncMock(),
        template_id="world",
    )


@pytest.mark.asyncio
async def test_stages_assemble_existing_schema_and_bind_private_inventory(plan, storage):
    llm = FakeLLM(plan)
    generation = runner(llm, storage)
    world = await generation.run()
    assert [call["phase"] for call in llm.calls] == [
        "plan",
        "protagonist",
        "scenes:0",
        "npcs:0",
        "objects:0",
    ]
    assert world.npcs[0].inventory == ["LETTER"]
    assert world.protagonist.starting_inventory == []
    assert world.scenes[0].id == "CITY"
    assert world.quests == world.scripts == []
    assert world.can_damage_npcs is False
    assert llm.max_tokens == 8192
    assert "Checking world references" in generation.status.call_args.args[0]
    assert set(storage[1].generation_checkpoint["results"]) == {call["phase"] for call in llm.calls}


@pytest.mark.asyncio
async def test_fresh_runner_resumes_only_failed_stage_with_new_model(plan, storage):
    first = FakeLLM(plan, fail="objects:0")
    with pytest.raises(TimeoutError):
        await runner(first, storage).run()
    assert first.max_tokens == 8192
    assert "objects:0" not in storage[1].generation_checkpoint["results"]
    canonical = deepcopy(storage[1].generation_checkpoint["results"]["plan"])
    second = FakeLLM(plan)
    second.model = "replacement-model"
    await runner(second, storage).run()
    assert [call["phase"] for call in second.calls] == ["objects:0"]
    assert second.calls[0]["model"] == "replacement-model"
    assert storage[1].generation_checkpoint["results"]["plan"] == canonical


@pytest.mark.asyncio
async def test_new_input_invalidates_old_checkpoints(plan, storage):
    await runner(FakeLLM(plan), storage).run()
    changed = FakeLLM(plan)
    await runner(changed, storage, prompt="A changed premise").run()
    assert changed.calls[0]["phase"] == "plan"


@pytest.mark.asyncio
async def test_invalid_batch_retries_once_and_never_enters_checkpoint(plan, storage):
    llm = FakeLLM(plan, bad_id=True)
    with pytest.raises(ValueError, match="invalid data twice"):
        await runner(llm, storage).run()
    assert [call["phase"] for call in llm.calls].count("objects:0") == 2
    assert "objects:0" not in storage[1].generation_checkpoint["results"]
    assert "Validation feedback" in llm.calls[-1]["user_prompt"]
    assert llm.max_tokens == 8192


@pytest.mark.asyncio
async def test_cancelled_response_cannot_be_checkpointed(plan, storage, monkeypatch):
    from backend.models.adventure_template import GenerationCancelled

    llm = FakeLLM(plan)
    generation = runner(llm, storage)
    checks = AsyncMock(side_effect=[None, None, None, GenerationCancelled("cancelled")])
    monkeypatch.setattr(generation.store, "check", checks)
    with pytest.raises(GenerationCancelled):
        await generation.run()
    assert generation.store.results == {}
    assert llm.max_tokens == 8192


def test_context_preserves_distant_canon_and_related_private_details(plan):
    plan["scenes"][0]["summary"] = "A distant unresolved mystery"
    context = detail_context(
        plan,
        "objects",
        plan["objects"],
        {
            "npcs:0": {
                "items": [
                    dict(
                        id="LENA", start_scene_id="TAVERN", goal="Secret plan", inventory=["LETTER"]
                    )
                ]
            }
        },
    )
    assert "distant unresolved mystery" in context
    assert "Secret plan" in context
    assert "Russian" in context


def test_cast_history_is_shared_even_across_different_locations(plan):
    context = detail_context(
        plan,
        "scenes",
        [plan["scenes"][0]],
        {
            "npcs:0": {
                "items": [
                    dict(
                        id="LENA",
                        start_scene_id="TAVERN",
                        description="Sister of the mayor",
                        goal="Secret plan",
                    )
                ]
            }
        },
    )
    assert "Sister of the mayor" in context
    assert "Secret plan" in context


@pytest.mark.asyncio
async def test_requested_scene_count_is_checked_before_detail_calls(plan, storage):
    generation = runner(FakeLLM(plan), storage)
    generation.metadata = {"min_scenes": 3}
    with pytest.raises(ValueError, match="invalid data twice"):
        await generation.run()
    assert [call["phase"] for call in generation.llm.calls] == ["plan", "plan"]


@pytest.mark.asyncio
async def test_invalid_saved_detail_is_regenerated_without_losing_siblings(plan, storage):
    await runner(FakeLLM(plan), storage).run()
    storage[1].generation_checkpoint["results"]["npcs:0"]["items"][0]["name"] = "Wrong person"
    llm = FakeLLM(plan)
    await runner(llm, storage).run()
    assert [call["phase"] for call in llm.calls] == ["npcs:0"]


@pytest.mark.asyncio
async def test_invalid_saved_plan_invalidates_all_dependent_details(plan, storage):
    await runner(FakeLLM(plan), storage).run()
    storage[1].generation_checkpoint["results"]["plan"]["scenes"] = []
    llm = FakeLLM(plan)
    await runner(llm, storage).run()
    assert len(llm.calls) == 5


@pytest.mark.asyncio
async def test_disabled_quests_ignore_stale_minimum_setting(plan, storage):
    generation = runner(FakeLLM(plan), storage, mode="rpg")
    generation.metadata = {"quest_generation_enabled": False, "min_quests": 3}
    world = await generation.run()
    assert world.quests == []
