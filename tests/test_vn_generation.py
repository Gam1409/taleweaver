"""VN creation and import must not silently re-enable RPG progression."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.adventure_creation import CoverSource, build_template
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.core.adventure_format import CURRENT_VERSION
from backend.core.game_modes import is_vn, mode_policy
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.vn_world_generation import normalize_vn_generated_manifest
from backend.engine.world_generator import WorldGenerator
from backend.engine.world_prompt_builder import build_world_generation_prompts
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User

_REAL_GENERATE_WORLD = WorldGenerator.generate_world


@pytest.mark.parametrize("strict", [None, True, False])
def test_vn_policy_overrides_legacy_strict_flag(strict):
    policy = mode_policy("vn", strict)
    assert policy.vn
    assert not any(
        (policy.mechanics, policy.combat, policy.quests, policy.awards, policy.experience)
    )
    assert is_vn({"rule_enforcement_mode": "vn"})
    assert is_vn(SimpleNamespace(rule_enforcement_mode="vn"))


@pytest.mark.parametrize(
    ("mode", "strict", "mechanics", "combat", "quests"),
    [
        ("rpg", None, True, True, True),
        ("story", None, True, False, True),
        ("chat", None, False, False, False),
        ("strict", False, False, False, True),
        (None, False, False, True, True),
        ("chat", True, True, False, False),
    ],
)
def test_existing_modes_keep_legacy_behavior(mode, strict, mechanics, combat, quests):
    policy = mode_policy(mode, strict)
    assert (policy.mechanics, policy.combat, policy.quests) == (mechanics, combat, quests)
    assert policy.experience
    assert not policy.vn


def test_vn_creation_does_not_adopt_rpg_defaults():
    payload = CreateAdventureTemplatePayload(
        title="Evening conversation",
        rule_enforcement_mode="vn",
        award_generation_enabled=True,
        sequences=[{"id": "SEQ_1", "exp_reward": 100}],
    )
    template = build_template(payload, "vn-template", "owner", CoverSource())
    assert template.rule_enforcement_mode == "vn"
    assert template.strict_rules is False
    assert template.quest_generation_enabled is False
    assert template.award_generation_enabled is False
    assert template.can_damage_npcs is False
    assert template.npcs_can_damage_protagonist is False
    assert template.sequences == []


def _prompts(mode):
    return build_world_generation_prompts(
        title="A reunion",
        original_prompt="Friends meet after years apart.",
        language="Russian",
        selected_tone="Bittersweet",
        automatic_npc_voice_assignment=False,
        available_voice_list=None,
        can_damage_npcs=True,
        npcs_can_damage_protagonist=True,
        quest_generation_enabled=True,
        min_scenes=None,
        max_scenes=None,
        min_quests=None,
        max_quests=None,
        award_generation_enabled=True,
        min_awards=None,
        max_awards=None,
        container_generation_enabled=True,
        min_containers=None,
        max_containers=None,
        text_log_generation_enabled=True,
        min_text_logs=None,
        max_text_logs=None,
        min_items=None,
        max_items=None,
        cover_source_manifest=None,
        cover_source_adventure_name=None,
        cover_similarity_percent=0,
        allow_reuse_source_assets=False,
        rule_enforcement_mode=mode,
    )


def test_vn_prompt_has_no_contradictory_mandatory_rpg_sections():
    system, user = _prompts("vn")
    combined = system + user
    assert "stable values, boundaries, voice" in system
    assert "Russian" in system
    assert "schema keys, enums" in system
    assert "Bittersweet" in user
    assert "LINEAR CHAPTERS" not in combined
    assert "SPECIAL ATTACKS (turn-based combat)" not in combined
    assert "Use lock mechanics frequently" not in combined
    assert "typically between 3 and 8" not in combined
    assert "LINEAR CHAPTERS" in "".join(_prompts("rpg"))


def test_vn_manifest_rejects_generated_progression_but_keeps_character_identity():
    manifest = {
        "quests": [{"exp_reward": 50}],
        "awards": [{"key": "WIN"}],
        "sequences": [{"exp_reward": 100}],
        "scripts": [{"id": "XP"}],
        "init_script": "tw.add_xp(10)",
        "completed_condition": "Win",
        "protagonist": {"name": "Alex", "goal": "Reconcile", "special_actions": [{}]},
        "npcs": [
            {"id": "LENA", "character": "Patient; values honesty", "attack_mode": "ATTACK_ON_SIGHT"}
        ],
    }
    normalize_vn_generated_manifest(manifest)
    assert all(manifest[k] == [] for k in ("quests", "awards", "sequences", "scripts"))
    assert manifest["init_script"] is None
    assert manifest["completed_condition"] == ""
    assert manifest["protagonist"]["goal"] == "Reconcile"
    assert manifest["npcs"][0]["character"] == "Patient; values honesty"
    assert manifest["npcs"][0]["attack_mode"] == "PASSIVE"


@pytest.mark.asyncio
async def test_vn_adv_import_export_preserves_mode_without_walkthrough_xp(
    auth_client, setup_test_db
):
    from tests.conftest import TestSessionLocal

    payload = {
        "format": "TaleWeaver",
        "version": "1.2",
        "adventure": {
            "title": "VN roundtrip",
            "rule_enforcement_mode": "vn",
            "strict_rules": True,
            "plot": "A friendship under strain",
            "walkthrough": "An old RPG outline",
            "can_damage_npcs": True,
            "npcs_can_damage_protagonist": True,
        },
        "protagonist": {"name": "Alex", "role": "Neighbour", "description": "A visitor"},
        "scenes": [{"id": "START", "label": "Cafe", "description": "A quiet table"}],
        "npcs": [],
        "objects": [],
        "exits": [],
        "quests": [{"id": "Q1", "exp_reward": 50}],
        "awards": [{"key": "A1"}],
        "sequences": [{"id": "SEQ_1", "exp_reward": 100}],
    }
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalars().first()
        assert await AdventureTemplateImporter.import_adv_manifest(db, payload, owner_id=user.id)
        template = (
            (
                await db.execute(
                    select(AdventureTemplate).where(AdventureTemplate.title == "VN roundtrip")
                )
            )
            .scalars()
            .one()
        )
        exported = await AdventureExporter.build_full_manifest(db, template.id)
        assert exported["adventure"]["rule_enforcement_mode"] == "vn"
        assert template.strict_rules is False
        assert template.quests == template.awards == template.sequences == []
        assert template.can_damage_npcs is False
        assert template.npcs_can_damage_protagonist is False
        assert exported["quests"] == exported["awards"] == exported["sequences"] == []


@pytest.mark.asyncio
async def test_edit_vn_rejects_strict_flag_override(auth_client, setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalars().first()
        db.add(
            AdventureTemplate(
                id="vn-edit", owner_id=user.id, title="VN edit", rule_enforcement_mode="rpg"
            )
        )
        await db.commit()
    response = await auth_client.patch(
        "/api/adventures/vn-edit",
        json={
            "rule_enforcement_mode": "vn",
            "strict_rules": True,
            "can_damage_npcs": True,
            "award_generation_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["strict_rules"] is False
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "vn-edit")
        assert template.award_generation_enabled is False
        assert template.can_damage_npcs is False


def test_vn_validation_does_not_request_rpg_endings_or_walkthrough():
    from backend.api.routes.adventures.editing.validation import _build_ai_validation_prompt
    from backend.core.world_validation.context import ValidationContext
    from backend.core.world_validation.story import check_story_fields

    payload = {
        "adventure": {
            "rule_enforcement_mode": "vn",
            "title": "Reunion",
            "plot": "A difficult reunion",
            "intro_text": "A familiar visitor waits",
            "teaser": "A promise remembered",
            "rules": "Respect personal knowledge and boundaries. " * 4,
        }
    }
    findings = check_story_fields(ValidationContext.from_payload(payload))
    assert findings == []
    assert "intentional, not missing content" in _build_ai_validation_prompt(payload)
    payload["adventure"]["rule_enforcement_mode"] = "rpg"
    findings = check_story_fields(ValidationContext.from_payload(payload))
    assert {f.context["field"] for f in findings} == {
        "walkthrough",
        "completed_condition",
        "gameover_condition",
    }


@pytest.mark.asyncio
async def test_generator_threads_vn_prompt_and_sanitizes_before_apply(monkeypatch):
    from unittest.mock import AsyncMock

    manifest = {
        "protagonist": {"name": "Alex", "special_actions": [{}]},
        "scenes": [],
        "exits": [],
        "npcs": [],
        "objects": [],
        "quests": [{"exp_reward": 100}],
        "awards": [{"key": "BONUS"}],
        "sequences": [{"id": "SEQ_1", "exp_reward": 100}],
        "scripts": [{"id": "FORCED_FIGHT"}],
    }
    generated = SimpleNamespace(
        model_dump=lambda: manifest, scenes=[], exits=[], npcs=[], objects=[]
    )
    llm = SimpleNamespace(
        provider="ollama", model="test", aexecute_complex_task=AsyncMock(return_value=generated)
    )
    monkeypatch.setattr(
        "backend.engine.world_generator.GameMasterLLM.for_role", lambda *a, **k: llm
    )
    generate = AsyncMock(return_value=generated)
    monkeypatch.setattr("backend.engine.staged_world.generate_manifest", generate)
    apply = AsyncMock()
    monkeypatch.setattr("backend.engine.world_manifest_applier.apply_manifest", apply)
    db = AsyncMock()
    db.get.return_value = None
    user = SimpleNamespace(llm_settings={"generator_model_provider": "ollama"}, tts_settings={})

    await _REAL_GENERATE_WORLD(
        db=db,
        user=user,
        template_id="vn-direct",
        title="Reunion",
        original_prompt="A meeting",
        rule_enforcement_mode="vn",
        language="Japanese",
    )

    request = generate.call_args.kwargs
    assert request["mode"] == "vn"
    assert request["llm"] is llm
    assert "interactive visual novel" in request["system_prompt"]
    assert "Japanese" in request["system_prompt"]
    assert request["metadata"]["quest_generation_enabled"] is False
    applied = apply.call_args.args[2]
    assert applied["format_version"] == CURRENT_VERSION
    assert applied["quests"] == applied["awards"] == applied["sequences"] == []
    assert applied["scripts"] == []
    assert applied["can_damage_npcs"] is False
    assert applied["protagonist"]["special_actions"] == []


def test_generator_service_keeps_legacy_mode_default_and_accepts_vn():
    from backend.engine.adventure_generator_service import _create_initial_template
    from backend.engine.rule_engine import AdventureGenerationRequest

    user = SimpleNamespace(id="owner")
    legacy = AdventureGenerationRequest(title="Story", prompt="A premise")
    legacy_template = _create_initial_template("legacy", user, legacy, False)
    assert legacy_template.rule_enforcement_mode == "strict"
    assert legacy_template.strict_rules is True
    vn = AdventureGenerationRequest(title="Story", prompt="A premise", rule_enforcement_mode="vn")
    vn_template = _create_initial_template("vn", user, vn, False)
    assert vn_template.rule_enforcement_mode == "vn"
    assert vn_template.strict_rules is False
    assert vn_template.quest_generation_enabled is False
