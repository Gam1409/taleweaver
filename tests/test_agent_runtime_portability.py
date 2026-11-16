"""Opaque ADV/ADZ data survives storage; public preparation reports runtime fallback."""

import io
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.config import settings
from backend.core.manifest_extensions import (
    MAX_EXTENSIONS_BYTES,
    normalize_extensions,
    preserve_extensions,
)
from backend.engine.adventure_compat import (
    CompatibilityError,
    export_upstream_manifest,
    import_upstream_manifest,
)
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.authoring_settings import preserve_authoring_settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.schemas.adventure_import import AdventureTemplateImportPayload
from tests.conftest import TestSessionLocal


def manifest():
    return {
        "format": "TaleWeaver",
        "version": "1.3",
        "adventure": {
            "title": "Portable agents",
            "version": "1.0.0",
            "origin_id": "69d62242-c2cc-4716-8473-a24502955d35",
            "rule_enforcement_mode": "chat",
        },
        "scenes": [{"id": "ROOM", "name": "Room", "description": "A room"}],
        "npcs": [
            {
                "id": "GUIDE",
                "name": "Guide",
                "description": "A guide",
                "start_scene_id": "ROOM",
                "metadata_json": {"agent_runtime": {"schema_version": 1, "future": {"null": None}}},
            }
        ],
        "extensions": {
            "agent_runtime": {"schema_version": 1, "future": {"null": None}},
            "other_runtime": {"code": "opaque, not Python", "path": "assets/not-packed.bin"},
        },
    }


def test_namespace_limits_match_upstream_value_budget():
    assert len(normalize_extensions({f"ns{i}": {} for i in range(33)})) == 32
    raw = {
        "a" * 64: {},
        "a" * 65: {},
        "Upper": {},
        "invalid/slash": {},
        "not_object": [],
        "ok": {"n": None},
    }
    assert set(normalize_extensions(raw)) == {"a" * 64, "ok"}
    # Upstream's byte budget counts serialized namespace values with ensure_ascii=False.
    prefix_size = len(json.dumps({"x": ""}, ensure_ascii=False).encode())
    remaining = MAX_EXTENSIONS_BYTES - prefix_size
    data = {"x": "я" * (remaining // 2) + "a" * (remaining % 2)}
    assert len(json.dumps(data, ensure_ascii=False).encode()) == MAX_EXTENSIONS_BYTES
    assert normalize_extensions({"full": data, "later": {}}) == {"full": data}
    assert normalize_extensions({"too_big": {"x": data["x"] + "я"}, "small": {}}) == {"small": {}}


def test_schema_and_authoring_edits_preserve_unknown_fields_and_explicit_removal():
    original = manifest()
    schema = AdventureTemplateImportPayload.model_validate(
        {**original, "title": "Agents", "characters": original["npcs"]}
    )
    assert schema.extensions == original["extensions"]
    assert schema.characters[0].metadata_json == original["npcs"][0]["metadata_json"]
    edited = preserve_authoring_settings(
        {"plot": "An edit"}, SimpleNamespace(original_manifest=original)
    )
    assert edited["extensions"] == original["extensions"]
    assert "extensions" not in preserve_extensions({"extensions": {}}, original)
    edited["extensions"]["agent_runtime"]["future"]["null"] = "changed"
    assert original["extensions"]["agent_runtime"]["future"]["null"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("archive", [False, True])
async def test_real_import_edit_export_roundtrip(auth_client, monkeypatch, tmp_path, archive):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    for method in ("generate_placeholder", "generate_svg_placeholder", "ensure_thumbnails"):
        monkeypatch.setattr(
            f"backend.engine.media_engine.MediaEngine.{method}",
            AsyncMock(return_value="/data/fake.svg"),
        )
    original = manifest()
    before = deepcopy(original)
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User).limit(1))
        if archive:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as output:
                output.writestr("adventure.adv", json.dumps(original))
            success = await AdventureTemplateImporter.import_adz(
                db, data.getvalue(), owner_id=owner.id
            )
        else:
            success = await AdventureTemplateImporter.import_adv_manifest(
                db, deepcopy(original), owner_id=owner.id
            )
        assert success
        template = await db.scalar(
            select(AdventureTemplate).where(AdventureTemplate.title == "Portable agents")
        )
        template.title = "Edited agents"
        await db.commit()
        exported = await AdventureExporter.build_full_manifest(db, template.id)
        assert exported["extensions"] == before["extensions"]
        assert (
            exported["npcs"][0]["metadata_json"]["agent_runtime"]
            == before["npcs"][0]["metadata_json"]["agent_runtime"]
        )
        assert "session_state" not in exported
        adz = await AdventureExporter.export_adz(db, template.id)
        with zipfile.ZipFile(io.BytesIO(adz)) as bundle:
            assert "assets/not-packed.bin" not in bundle.namelist()
            assert json.loads(bundle.read("adventure.adv"))["extensions"] == before["extensions"]
    assert original == before


def test_compatibility_converters_keep_opaque_extensions_and_report_behavioral_fallback():
    original = manifest()
    converted, report = export_upstream_manifest(original)
    assert report.requires_acknowledgement
    assert converted["extensions"] == original["extensions"]
    assert import_upstream_manifest(converted)["extensions"] == original["extensions"]
    assert converted["npcs"][0]["metadata_json"] == original["npcs"][0]["metadata_json"]


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"schema_version": 1, "fallback": "block"},
        {"schema_version": 1, "api_key": "SYNTHETIC"},
    ],
)
def test_public_preparation_blocks_unsupported_or_private_extension_data(change):
    original = manifest()
    original["extensions"]["agent_runtime"] = change
    with pytest.raises(CompatibilityError):
        export_upstream_manifest(original)
