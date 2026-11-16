"""AI-Fix must not invent a cloud destination or bypass an uncertain local request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from backend.api.routes.adventures.editing import ai_fix_llm, ai_fix_suggest
from backend.core.config import Settings, settings
from backend.core.inference import admission
from backend.core.inference.registry import InferenceUncertainError, Registry, endpoint_key
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_ai_fix_endpoint import _seed_simple_adventure


class Reply(BaseModel):
    value: str


def user(config=None):
    return SimpleNamespace(username="fixture", llm_settings=config or {})


def test_environment_cloud_fallback_is_disabled_by_default():
    assert Settings.model_fields["AI_FIX_FALLBACK_PROVIDER"].default == ""


def test_no_role_configuration_never_invents_an_openai_attempt(monkeypatch):
    monkeypatch.setattr(settings, "AI_FIX_FALLBACK_PROVIDER", "")
    assert ai_fix_llm._candidate_attempts(user(), True) == []


async def test_no_role_configuration_returns_an_actionable_error_without_a_model_call(monkeypatch):
    monkeypatch.setattr(settings, "AI_FIX_FALLBACK_PROVIDER", "")
    factory = AsyncMock()
    monkeypatch.setattr(ai_fix_llm, "_init_provider", factory)
    with pytest.raises(ai_fix_llm._AllProvidersFailedError) as caught:
        await ai_fix_llm._generate_llm_proposals(
            user_prompt="Fixture",
            current_user=user(),
            response_model=Reply,
            gm_kwargs={"system_prompt": "Fixture"},
        )
    assert "Choose a model" in ai_fix_llm._summarize_outcomes(caught.value.outcomes)
    factory.assert_not_called()


async def test_served_provider_is_returned_and_retained_on_cache_hits(auth_client, monkeypatch):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User))
        template = await _seed_simple_adventure(db, owner=owner)
        await db.commit()
    wrapper = SimpleNamespace(
        proposals=[
            {
                "title": "Clarify the librarian",
                "summary": "Describe the NPC more clearly.",
                "patches": [
                    {
                        "target_type": "npc",
                        "target_id": "OLD_LIBRARIAN",
                        "field_updates": {"description": "A careful keeper of the archive."},
                    }
                ],
            }
        ]
    )
    generate = AsyncMock(return_value=(wrapper, "ollama"))
    monkeypatch.setattr(ai_fix_suggest, "_generate_llm_proposals", generate)
    payload = {
        "finding_code": "npc_description",
        "finding_message": "Clarify this NPC.",
        "finding_location": "npc:OLD_LIBRARIAN",
    }
    for _ in range(2):
        response = await auth_client.post(
            f"/api/adventures/{template}/editor/validate/findings/suggest-fix", json=payload
        )
        assert response.status_code == 200, response.text
        assert response.json()["served_provider"] == "ollama"
        assert response.json()["proposals"]
    generate.assert_awaited_once()


@pytest.mark.parametrize("uncertain", [True, False])
async def test_uncertain_request_never_advances_to_another_endpoint(
    monkeypatch, tmp_path, uncertain
):
    monkeypatch.setattr(settings, "AI_FIX_FALLBACK_PROVIDER", "")
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    registry = Registry(tmp_path / "requests.json")
    monkeypatch.setattr(admission, "registry", lambda: registry)
    error = (
        InferenceUncertainError("Completion is unconfirmed")
        if uncertain
        else TimeoutError("Read timed out")
    )
    primary = SimpleNamespace(
        model="mock",
        provider="custom_openai",
        api_base="http://fixture.invalid:1234/v1",
        aexecute_complex_task=AsyncMock(side_effect=error),
    )
    fallback = SimpleNamespace(
        model="mock",
        provider="ollama",
        aexecute_complex_task=AsyncMock(return_value=Reply(value="should not run")),
    )
    if not uncertain:
        ticket = registry.enqueue(endpoint_key(primary.api_base))
        assert registry.try_acquire(ticket, background_ready=True)
        registry.finish(ticket, certain=False)
    monkeypatch.setattr(
        ai_fix_llm,
        "_init_provider",
        lambda _user, _provider, _model, role: (
            primary if role == "complex" else fallback,
            None,
            None,
        ),
    )
    configured = user(
        {
            "complex_model_provider": "custom_openai",
            "complex_model": "mock",
            "small_model_provider": "ollama",
            "small_model": "mock",
        }
    )
    with pytest.raises(InferenceUncertainError):
        await ai_fix_llm._generate_llm_proposals(
            user_prompt="Fixture",
            current_user=configured,
            response_model=Reply,
            gm_kwargs={"system_prompt": "Fixture"},
        )
    primary.aexecute_complex_task.assert_awaited_once()
    fallback.aexecute_complex_task.assert_not_awaited()
