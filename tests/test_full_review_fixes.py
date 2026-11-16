"""Temporary audit probes: assert observed behavior, covering the corrected review findings."""

import asyncio
import io
import json
import sqlite3
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import _set_sqlite_pragmas
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.inference import admission, transport
from backend.core.inference.registry import InferenceUncertainError, Registry
from backend.core.llm_router import GameMasterLLM
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.rule_engine import GameEvent, RuleEngine
from backend.engine.scene_illustrations import render
from backend.engine.scripting.sandbox import (
    SafeAstInterpreter,
    ScriptExecutionError,
    ScriptSecurityError,
)
from backend.engine.skill_check import roll_dice_detailed
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from tests.conftest import TestSessionLocal


def test_f02_connect_hook_leaves_foreign_keys_disabled():
    with sqlite3.connect(":memory:") as connection:
        _set_sqlite_pragmas(connection, None)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


async def test_f15_cancel_propagates_but_leaves_uncertain_reservation(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "admission.json")
    monkeypatch.setattr(admission, "_registry", registry)
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    entered = asyncio.Event()

    async def chunks():
        entered.set()
        await asyncio.Event().wait()
        yield None

    @transport.guarded_async
    async def call(router, kwargs):
        return chunks()

    router = SimpleNamespace(
        provider="ollama", api_base="http://localhost:11434", request_timeout=2
    )
    stream = await call(router, {"stream": True})
    task = asyncio.create_task(anext(stream))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(InferenceUncertainError):
        other = await call(router, {"stream": True})
        await anext(other)


def test_f17_unknown_voice_tag_is_rewritten():
    assert GameMasterLLM.normalize_voice_tags("[Усмехнувшись] Привет") == "[Усмехнувшись] Привет"


def test_f22_fence_inside_json_string_corrupts_document():
    source = json.dumps({"text_log_content": "Example ```json {} ```"}, ensure_ascii=False)
    assert GameMasterLLM._clean_json_string(source) == source


def test_f29_dice_count_exceeds_existing_special_attack_cap():
    with pytest.raises(ValueError):
        roll_dice_detailed("51d6")


def test_f31_resource_delta_can_exceed_avatar_maximum():
    avatar = SimpleNamespace(
        hp=90, max_hp=100, stamina=90, max_stamina=100, mana=90, max_mana=100, status_effects=[]
    )
    RuleEngine.apply_event(avatar, GameEvent(hp_change=30))
    assert avatar.hp == 100


async def test_f38_equal_json_assignment_does_not_dirty_orm_columns():
    async with TestSessionLocal() as db:
        avatar = Avatar(
            id="audit-avatar",
            user_id="audit-user",
            name="Audit",
            inventory=[{"id": "x"}],
            equipment={"Head": None},
        )
        db.add(avatar)
        await db.commit()
        avatar.inventory = jsonable_encoder(avatar.inventory)
        avatar.equipment = jsonable_encoder(avatar.equipment)
        assert not db.is_modified(avatar, include_collections=True)
        await db.flush()


async def test_f51_disabled_preset_still_passes_enabled_policy_to_adapter(monkeypatch):
    captured = []
    monkeypatch.setattr(render, "prompt_rules", lambda _: ImagePromptRules(adapt_with_llm=False))

    async def adapter(source, policy, user, **kwargs):
        captured.append(policy.adapt_with_llm)
        return "A quiet empty room."

    monkeypatch.setattr(render, "adapt_body", adapter)
    request = {
        "provider": "comfyui",
        "provider_options": {"_prompt_user": object()},
        "prompt": "SCENE DATA: {}",
    }
    await render.prepare_moment_prompt(request)
    assert captured == [True]
    assert request["prompt"] == "A quiet empty room."


async def test_f63_failed_overwrite_does_not_restore_old_template_or_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    asset = tmp_path / "adventures" / "library" / "audit-old" / "cover.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"audit-fixture")
    async with TestSessionLocal() as db:
        db.add(AdventureTemplate(id="audit-old", title="Audit overwrite"))
        await db.commit()

        async def failing_apply(**kwargs):
            raise RuntimeError("Injected audit failure after overwrite deletion")

        monkeypatch.setattr(WorldGenerator, "apply_manifest", failing_apply)
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                "adventure.adv",
                json.dumps(
                    {
                        "format": "TaleWeaver",
                        "version": "1.3",
                        "adventure": {"title": "Audit overwrite"},
                    }
                ),
            )
        assert not await AdventureTemplateImporter.import_adz(db, buffer.getvalue(), overwrite=True)
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(select(AdventureTemplate.id).where(AdventureTemplate.id == "audit-old"))
            == "audit-old"
        )
    assert asset.exists()


def test_f67_string_statement_breaks_loop():
    scope = {}
    SafeAstInterpreter().execute(
        "out = 0\nfor k in range(5):\n    if True:\n        'break'\n    out += 1", scope
    )
    assert scope["out"] == 5


def test_f68_reserved_api_binding_is_copied_back():
    scope = {"tw": object(), "game": object()}
    with pytest.raises(ScriptSecurityError):
        SafeAstInterpreter().execute("tw = 7", scope)
    assert not isinstance(scope["tw"], int)


def test_f70_recursion_error_escapes_interpreter():
    with pytest.raises(ScriptExecutionError):
        SafeAstInterpreter().execute("def f():\n    return f()\nf()", {})


def test_f71_format_specification_is_ignored():
    scope = {}
    with pytest.raises(ScriptExecutionError):
        SafeAstInterpreter().execute('value = f"{1.5:.2f}"', scope)
