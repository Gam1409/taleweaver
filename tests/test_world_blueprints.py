"""Authored constraints enter staged planning, remain typed and never bypass ownership rules."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.engine.blueprint import BlueprintError, apply_blueprint, prepare_blueprint
from backend.engine.blueprint.generation import (
    prepare_generation_blueprint,
    prepare_generation_brief,
)
from backend.engine.blueprint.stages import bind_plan
from backend.models.adventure_template import AdventureTemplate
from tests.conftest import TestSessionLocal
from tests.test_staged_world_generation import FakeLLM, plan, runner, storage

__all__ = ["plan", "storage"]

TEXT = """A reunion after a long absence.
[Scene: CITY] Rainy city
description: ~Wet stone and familiar faces.
[Scene: TAVERN] Quiet tavern
[NPC: LENA] Doctor Lena
in: TAVERN
age: 32
gender: female
goal: Protect the letter until she can verify its origin.
character: Independent and reserved; evidence matters more than flattery.
inventory: LETTER
[Item: LETTER] Sealed letter
in: TAVERN
description: ?
"""


def test_fixed_hinted_open_values_keep_existing_identity_fields():
    prepared = prepare_blueprint(TEXT)
    lena = prepared.blueprint.first("npc")
    assert lena.fixed()["age_years"] == 32
    assert lena.fixed()["gender"] == "female"
    assert lena.fixed()["inventory"] == ["LETTER"]
    assert prepared.blueprint.first("scene").hints()["description"].startswith("Wet stone")
    assert "description" in prepared.blueprint.first("item").open_fields
    assert "AUTHOR BLUEPRINT" in prepared.prompt_section("strict")


def test_markdown_and_clothing_use_real_fork_schema():
    prepared = prepare_blueprint("""## Scene: LAB — Observatory
## NPC: MIRA — Mira
age: 28
in: LAB
## Item: COAT — White coat
in: LAB
clothing: {"layer": 2, "coverage": ["torso", "arms"], "underwear": false}
""")
    garment = prepared.blueprint.first("item").fixed()["clothing"]
    assert garment["layer"] == 2
    assert garment["coverage"] == ["torso", "arms"]


@pytest.mark.parametrize(
    "text, message",
    [
        ("[NPC: A] One\nage: -1", "age"),
        ("[NPC: A] One\nage: 1.5", "whole number"),
        ("[NPC: A] One\n[NPC: A] Two", "Duplicate"),
        ("[Item: COAT] Coat\nclothing: {broken", "JSON"),
        ("[Scene: LAB] Lab\non_enter: import os", "Import"),
        ("[Exit: LAB -> HALL] Door\nguard: __import__('os')", "__import__"),
        ("[Protagonist] Hero\n  [Talent: READ] Mind reading", "not supported"),
    ],
)
def test_invalid_blueprints_fail_preflight(text, message):
    with pytest.raises(BlueprintError, match=message):
        prepare_blueprint(text)


def test_fenced_scripts_are_copied_without_execution():
    prepared = prepare_blueprint("""[Script: NOTE] Remember
trigger: on_turn_start
code:
```python
tw.vars.set("seen", True)
```
""")
    assert prepared.blueprint.first("script").fixed()["code"] == 'tw.vars.set("seen", True)'


def test_bold_keys_preserve_bare_value_underscores_and_chapter_numbers_are_explicit():
    prepared = prepare_blueprint("[NPC: MIRA] Mira\n**age:** 28\ncharacter: __quiet__")
    assert prepared.blueprint.first("npc").fixed()["age_years"] == 28
    assert prepared.blueprint.first("npc").fixed()["character"] == "__quiet__"
    with pytest.raises(BlueprintError, match="consecutive"):
        prepare_blueprint("[Sequence: 4] Wrong number")
    with pytest.raises(BlueprintError, match="Nested"):
        prepare_blueprint(
            '[Sequence: 1] Opening\n  [Script: NOTE] Note\n  code: tw.vars.set("seen", True)'
        )


def test_mode_flags_and_counts_report_conflicts_before_generation():
    with pytest.raises(BlueprintError, match="maximum"):
        prepare_generation_blueprint(TEXT, {"max_scenes": 1})
    with pytest.raises(BlueprintError, match="VN mode"):
        prepare_generation_blueprint(
            "[Sequence: 1] Intro\nguard: tw.vars.get('seen')", {"rule_enforcement_mode": "vn"}
        )
    with pytest.raises(BlueprintError, match="disabled"):
        prepare_generation_blueprint(
            "[Container: BAG] Bag", {"container_generation_enabled": False}
        )


def test_plain_text_and_legacy_vn_outline_keep_their_behavior():
    assert prepare_blueprint("A quiet story in the city.") is None
    text, sequences, prepared = prepare_generation_brief(
        "A quiet story.\n[Sequence: 1] Reunion\nMeet an old friend.",
        None,
        {"rule_enforcement_mode": "vn"},
    )
    assert prepared is None
    assert "quiet story" in text
    assert sequences[0]["title"] == "Reunion"


def test_conflicting_ownership_and_missing_plan_entities_are_explicit(plan):
    blueprint = prepare_blueprint(TEXT).blueprint
    copy = deepcopy(plan)
    bind_plan(copy, blueprint)
    assert copy["npcs"][0]["name"] == "Doctor Lena"
    assert copy["objects"][0]["owner_id"] == "LENA"
    copy["npcs"] = []
    with pytest.raises(ValueError, match="omitted declared npc"):
        bind_plan(copy, blueprint)


@pytest.mark.asyncio
async def test_stages_reapply_author_fields_and_reuse_validated_checkpoints(plan, storage):
    llm = FakeLLM(plan)
    pipeline = runner(llm, storage, mode="story", prompt=TEXT)
    pipeline.blueprint = prepare_blueprint(TEXT).blueprint
    result = await pipeline.run()
    assert result.npcs[0].name == "Doctor Lena"
    assert result.npcs[0].age_years == 32
    assert "evidence matters" in result.npcs[0].character
    assert result.npcs[0].inventory == ["LETTER"]
    assert result.scenes[0].name == "Rainy city"
    count = len(llm.calls)
    second = await pipeline.run()
    assert second == result
    assert len(llm.calls) == count


@pytest.mark.asyncio
async def test_merge_failure_leaves_the_supplied_manifest_unchanged(plan, storage):
    generated = (await runner(FakeLLM(plan), storage).run()).model_dump()
    before = deepcopy(generated)
    with pytest.raises(ValueError, match="omitted declared"):
        apply_blueprint(generated, prepare_blueprint("[NPC: ABSENT] Missing person").blueprint)
    assert generated == before


@pytest.mark.asyncio
async def test_preflight_api_reports_line_numbers_and_never_calls_a_model(auth_client, monkeypatch):
    llm = AsyncMock(side_effect=AssertionError("Preflight must not call an LLM"))
    monkeypatch.setattr("backend.core.llm_router.GameMasterLLM.aexecute_complex_task", llm)
    response = await auth_client.post(
        "/api/adventures/blueprint/validate", json={"text": "[NPC: LENA] Lena\nage: -1"}
    )
    assert response.status_code == 200
    assert response.json()["errors"][0]["line"] == 2
    assert not llm.called
    assert (
        await auth_client.post(
            "/api/adventures/blueprint/validate",
            json={"text": TEXT, "options": {"max_scenes": "bad"}},
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_creation_rejects_invalid_blueprint_before_creating_records(auth_client):
    async with TestSessionLocal() as db:
        before = await db.scalar(select(func.count()).select_from(AdventureTemplate))
    response = await auth_client.post(
        "/api/adventures/",
        json={"title": "Invalid", "original_prompt": "[NPC: LENA] Lena\nage: -1"},
    )
    assert response.status_code == 422
    assert "line 2" in response.json()["detail"]
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AdventureTemplate)) == before
