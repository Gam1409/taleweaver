"""Portal creation and resumed jobs forward the DTO tone to the existing generator."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures import adventure_creation
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.models import AdventureTemplate, GameSession
from tests.conftest import TestSessionLocal
from tests.prompt_task_support import no_live_prompt_models

__all__ = ["no_live_prompt_models"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("mode", ["rpg", "story", "vn"])
@pytest.mark.parametrize(
    "tone",
    [
        {"id": "heroic-epic", "name": "Heroic & Epic", "instruction": "A hopeful quest."},
        "Horror",
        None,
    ],
)
async def test_portal_creation_forwards_and_persists_the_typed_tone(
    auth_client, monkeypatch, mode, tone
):
    generator = AsyncMock()
    monkeypatch.setattr(adventure_creation.WorldGenerator, "generate_world", generator)
    body = {"title": "Archive quest", "selected_tone": tone, "rule_enforcement_mode": mode}
    expected = CreateAdventureTemplatePayload.model_validate(body).selected_tone
    response = await auth_client.post("/api/adventures/", json=body)
    assert response.status_code == 201, response.text
    generator.assert_awaited_once()
    assert generator.call_args.kwargs["selected_tone"] == expected
    assert generator.call_args.kwargs["rule_enforcement_mode"] == mode
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, response.json()["adventure_id"])
        assert template.selected_tone == expected
        assert template.generation_request["payload"]["selected_tone"] == expected


async def test_resumed_generation_uses_saved_tone_and_keeps_original_session(
    auth_client, monkeypatch
):
    tone = {"id": "heroic-epic", "name": "Heroic & Epic", "instruction": "A hopeful quest."}
    generator = AsyncMock(side_effect=[RuntimeError("Synthetic first attempt failure"), None])
    monkeypatch.setattr(adventure_creation.WorldGenerator, "generate_world", generator)
    response = await auth_client.post(
        "/api/adventures/", json={"title": "Saved archive", "selected_tone": tone}
    )
    assert response.status_code == 201, response.text
    ids = response.json()
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, ids["adventure_id"])
        assert template.creation_status == "Failed"
        # Resume follows the saved request even if the stopped template was edited.
        template.selected_tone = {"id": "different", "name": "Different"}
        await db.commit()
    resumed = await auth_client.post(f"/api/adventures/{ids['adventure_id']}/resume-generation")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["game_id"] == ids["game_id"]
    assert generator.await_count == 2
    assert [call.kwargs["selected_tone"] for call in generator.await_args_list] == [tone, tone]
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, ids["adventure_id"])
        assert template.generation_request["payload"]["selected_tone"] == tone
        assert await db.scalar(select(func.count(GameSession.id))) == 1
        assert await db.scalar(select(func.count(AdventureTemplate.id))) == 1


async def test_skipped_generation_saves_tone_without_invoking_generator(auth_client, monkeypatch):
    generator = AsyncMock()
    monkeypatch.setattr(adventure_creation.WorldGenerator, "generate_world", generator)
    tone = {"id": "heroic-epic", "name": "Heroic & Epic"}
    response = await auth_client.post(
        "/api/adventures/",
        json={"title": "Authored archive", "selected_tone": tone, "skip_generation": True},
    )
    assert response.status_code == 201, response.text
    generator.assert_not_awaited()
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, response.json()["adventure_id"])
        assert template.selected_tone == tone
