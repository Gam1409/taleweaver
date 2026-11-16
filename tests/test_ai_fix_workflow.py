"""Actual suggestion → review → apply → reload contracts, including inner clothing."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.editing import ai_fix_llm, ai_fix_suggest
from backend.api.routes.adventures.editing.ai_fix_context import _signing
from backend.api.routes.adventures.editing.payload import _build_adventure_editor_assets
from backend.core.world_validator import validate_adventure
from backend.models.adventure_template import AdventureTemplate
from backend.models.ai_fix_cache import AIFixCache
from backend.models.avatar import Avatar
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.schemas.validation import AIFixSuggestionsRequest
from tests.ai_fix_fixture import NPC, OUTFIT, TEMPLATE, proposal, seed
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory

BASE = f"/api/adventures/{TEMPLATE}/editor"


def install_model(monkeypatch, result):
    calls = []

    class Model:
        def __init__(self, *args, **kwargs):
            pass

        async def aexecute_complex_task(self, *, response_model, **kwargs):
            calls.append(kwargs)
            return response_model.model_validate({"proposals": result})

    monkeypatch.setattr(ai_fix_llm, "GameMasterLLM", RoleLLMFactory(Model))
    return calls


async def prepare(kind="npc"):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User))
        request = await seed(db, owner)
        target = NPC
        if kind == "protagonist":
            target = (await db.scalar(select(Avatar).where(Avatar.template_id == TEMPLATE))).id
            assets = await _build_adventure_editor_assets(TEMPLATE, db)
            finding = next(
                f
                for f in validate_adventure(assets)
                if f.location == "protagonist:player" and f.code == "character_details_incomplete"
            )
            request = {
                "finding_code": finding.code,
                "finding_message": finding.message,
                "finding_location": finding.location,
                "finding_context": finding.context,
            }
        return owner.id, request, target


@pytest.mark.parametrize("kind", ["npc", "protagonist"])
async def test_suggestion_apply_and_reload_create_seven_owned_garments_without_duplicates(
    auth_client, monkeypatch, kind
):
    _, request, target = await prepare(kind)
    calls = install_model(monkeypatch, [proposal(kind, target)])
    for _ in range(2):
        response = await auth_client.post(BASE + "/validate/findings/suggest-fix", json=request)
        assert response.status_code == 200, response.text
        suggested = response.json()
        assert suggested["error"] is None and len(suggested["proposals"]) == 1
        assert len(suggested["proposals"][0]["patches"][0]["field_updates"]["outfit"]) == 7
    assert len(calls) == 1  # Reviewing a cached proposal costs no second model request.
    assert "AUTHORING COMPLETION" in calls[0]["user_prompt"]
    async with TestSessionLocal() as db:
        assert not list(
            await db.scalars(select(WorldEntity).where(WorldEntity.item_type == "WEARABLE"))
        )
    payload = {
        "finding_signature": suggested["finding_signature"],
        "proposal": suggested["proposals"][0],
    }
    for _ in range(2):
        applied = await auth_client.post(BASE + "/validate/findings/apply-fix", json=payload)
        assert applied.status_code == 200 and applied.json()["status"] == "applied", applied.text
    assert len(calls) == 1  # Apply and repeated apply must not call a model.
    async with TestSessionLocal() as db:
        model = WorldEntity if kind == "npc" else Avatar
        actor = await db.scalar(
            select(model).where(model.template_id == TEMPLATE, model.id == target)
        )
        clothes = list(
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.template_id == TEMPLATE, WorldEntity.item_type == "WEARABLE"
                )
            )
        )
        ids = {item.id for item in clothes}
        assert len(clothes) == len(actor.inventory) == len(actor.visual_profile["worn"]) == 7
        assert {item["id"] for item in actor.inventory} == ids
        assert {item["item_id"] for item in actor.visual_profile["worn"]} == ids
        assert sorted(
            item.name for item in clothes if item.metadata_json["clothing"]["underwear"]
        ) == ["Red silk bra", "Red silk briefs"]
        assert all(item.session_id is None and item.is_in_inventory for item in clothes)
        manifest = (await db.get(AdventureTemplate, TEMPLATE)).original_manifest
        assert {item["id"] for item in manifest["objects"]} == ids
        assert actor.age_years == (34 if kind == "npc" else 32)
    reloaded = await auth_client.get(BASE + "/assets")
    assert reloaded.status_code == 200 and len(reloaded.json()["objects"]) == 7


def test_unsupported_patch_fields_cannot_be_presented_as_an_applicable_fix():
    raw = proposal()["patches"][0]
    raw["field_updates"] = {"unsupported_field": "No actual change"}
    assert ai_fix_suggest._clean_patch(raw) is None


async def test_explicit_retry_bypasses_a_cached_proposal_and_calls_the_model_again(
    auth_client, monkeypatch
):
    _, request, _ = await prepare()
    options = [proposal()]
    calls = install_model(monkeypatch, options)
    first = await auth_client.post(BASE + "/validate/findings/suggest-fix", json=request)
    assert first.status_code == 200 and len(calls) == 1
    options[0] = proposal()
    options[0]["title"] = "A fresh corrected proposal"
    retried = await auth_client.post(
        BASE + "/validate/findings/suggest-fix", json={**request, "force_refresh": True}
    )
    assert retried.status_code == 200
    assert retried.json()["proposals"][0]["title"] == "A fresh corrected proposal"
    assert len(calls) == 2


async def test_unusable_model_proposals_report_an_error_and_are_not_cached(
    auth_client, monkeypatch
):
    _, request, _ = await prepare()
    invalid = proposal()
    invalid["patches"][0]["field_updates"] = {"unsupported_field": "No actual change"}
    calls = install_model(monkeypatch, [invalid])
    response = await auth_client.post(BASE + "/validate/findings/suggest-fix", json=request)
    assert response.status_code == 200
    assert response.json()["proposals"] == [] and response.json()["error"]
    async with TestSessionLocal() as db:
        assert not list(await db.scalars(select(AIFixCache)))
    assert len(calls) == 1


async def test_legacy_unusable_cache_is_evicted_on_noop_so_retry_can_generate(
    auth_client, monkeypatch
):
    owner_id, request, _ = await prepare()
    invalid = deepcopy(proposal())
    invalid["patches"][0]["field_updates"] = {"unsupported_field": "No actual change"}
    signature = _signing(AIFixSuggestionsRequest.model_validate(request))
    async with TestSessionLocal() as db:
        await ai_fix_llm._write_cached_suggestions(
            db=db,
            template_id=TEMPLATE,
            user_id=owner_id,
            signature=signature,
            response_payload={
                "finding_signature": signature,
                "proposals": [invalid],
                "generated_at": "2026-11-07T00:00:00Z",
            },
        )
    calls = install_model(monkeypatch, [proposal()])
    response = await auth_client.post(
        BASE + "/validate/findings/apply-fix",
        json={"finding_signature": signature, "proposal": invalid},
    )
    assert response.status_code == 200 and response.json()["status"] == "no_op"
    fresh = await auth_client.post(BASE + "/validate/findings/suggest-fix", json=request)
    assert (
        fresh.status_code == 200
        and fresh.json()["proposals"][0]["patches"][0]["field_updates"]["outfit"] == OUTFIT
    )
    assert len(calls) == 1
