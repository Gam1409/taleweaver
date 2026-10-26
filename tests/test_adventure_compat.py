"""Conversion contracts use real pinned upstream fixtures and synthetic private data."""

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from backend.engine.adventure_compat import (
    CompatibilityError,
    export_upstream_manifest,
    import_upstream_manifest,
)
from backend.schemas.adventure_import import AdventureTemplateImportPayload

FIXTURES = Path(__file__).parent / "fixtures" / "adventure_compat"


def manifest() -> dict:
    return {
        "format": "TaleWeaver",
        "version": "1.3",
        "adventure": {
            "title": "茶と約束",
            "version": "1.0.0",
            "rule_enforcement_mode": "rpg",
            "origin_id": "7417658a-b7c4-499d-8a49-2af2de85abc1",
            "creator": "Original author",
            "copyright": "Original notice",
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        },
        "protagonist": {
            "name": "旅人",
            "character": "Patient",
            "goal": "Find a friend",
            "starting_inventory": ["TEA"],
            "starting_equipment": {},
            "profile_image": "assets/hero.png",
        },
        "scenes": [{"id": "ROOM", "name": "Tea room", "description": "A quiet place"}],
        "npcs": [
            {
                "id": "FRIEND",
                "name": "Анна",
                "description": "An old friend",
                "character": "Generous",
                "goal": "Share tea",
                "notes": "Author-only backstory",
                "inventory": ["CUP"],
                "image_url": "assets/friend.png",
            }
        ],
        "objects": [
            {"id": "TEA", "name": "茶", "description": "Green tea", "is_portable": True},
            {"id": "CUP", "name": "Cup", "description": "Blue ceramic"},
        ],
        "scripts": [
            {
                "id": "WELCOME",
                "trigger": "on_enter_scene",
                "target_id": "ROOM",
                "code": "tw.narrate('Welcome')",
            }
        ],
        "init_script": "def welcome():\n    tw.narrate('Tea is ready')",
    }


def upstream_schema():
    name = "pinned_upstream_adventure_schema"
    spec = importlib.util.spec_from_file_location(name, FIXTURES / "upstream_import_schema.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.AdventureTemplateImportPayload


def test_publication_preserves_identity_authorship_and_gameplay():
    original = manifest()
    before = deepcopy(original)
    converted, report = export_upstream_manifest(original)
    assert original == before
    assert converted["adventure"] == original["adventure"]
    for key in ("protagonist", "npcs", "objects", "scripts", "init_script"):
        assert converted[key] == original[key]
    assert not report.warnings
    payload = {**converted, **converted["adventure"]}
    assert upstream_schema().model_validate(payload).title == "茶と約束"
    assert import_upstream_manifest(converted)["init_script"] == original["init_script"]


def test_actual_upstream_architect_fixture_imports_without_losing_content():
    original = json.loads((FIXTURES / "upstream_architect.adv").read_text())
    before = deepcopy(original)
    converted = import_upstream_manifest(original)
    assert original == before
    assert converted["adventure"]["title"] == original["adventure"]["title"]
    assert converted["scenes"] == original["scenes"]
    assert len(converted["npcs"]) == len(original["npcs"])
    AdventureTemplateImportPayload.model_validate({**converted, **converted["adventure"]})


def test_actual_upstream_choice_fixture_cannot_silently_lose_dialogs():
    original = json.loads((FIXTURES / "upstream_choice.adv").read_text())
    with pytest.raises(CompatibilityError, match="API unavailable"):
        import_upstream_manifest(original)


def test_vn_downgrade_requires_acknowledgement_and_preserves_possessions():
    original = manifest()
    original["adventure"]["rule_enforcement_mode"] = "vn"
    original["visual_presets"] = {"standard": "local-preset-id"}
    original["npc_card_settings"] = {"show_indicators": True}
    original["clothing_settings"] = {"enabled": True}
    original["npcs"][0]["visual_profile"] = {
        "version": 1,
        "appearance": {"hair": "black", "eyes": "brown"},
        "worn": [{"item_id": "CUP"}],
    }
    original["objects"][0]["metadata_json"] = {
        "clothing": {"layer": 1, "coverage": ["torso"]},
        "damage_dice": "1d4",
    }
    converted, report = export_upstream_manifest(original)
    assert report.requires_acknowledgement
    assert any("Visual Novel" in warning for warning in report.warnings)
    assert converted["adventure"]["rule_enforcement_mode"] == "chat"
    assert upstream_schema().model_validate({**converted, **converted["adventure"]})
    assert converted["npcs"][0]["inventory"] == ["CUP"]
    assert converted["npcs"][0]["appearance"] == "black, brown"
    assert converted["objects"][0]["metadata_json"] == {"damage_dice": "1d4"}
    assert "visual_presets" not in converted


def test_publication_removes_nested_credentials_and_runtime_memory():
    original = manifest()
    original["api_key"] = "SYNTHETIC_TOP_SECRET"
    original["npcs"][0]["metadata_json"] = {
        "special_chance": 40,
        "npc_journal": [{"text": "SYNTHETIC_PRIVATE_MEMORY"}],
        "apiKey": "SYNTHETIC_CAMEL_SECRET",
        "API_KEY": "SYNTHETIC_UPPER_SECRET",
        "ollama_url": "https://SYNTHETIC_PRIVATE_HOST.example",
        "provider_config": {"key": "SYNTHETIC_CONFIG_SECRET"},
    }
    original["protagonist"]["stats"] = {
        "strength": 10,
        "compressed_history": "SYNTHETIC_PRIVATE_STORY",
    }
    converted, report = export_upstream_manifest(original)
    assert "SYNTHETIC" not in json.dumps(converted)
    assert "SYNTHETIC" not in str(report)
    assert report.requires_acknowledgement
    assert converted["npcs"][0]["metadata_json"] == {"special_chance": 40}
    assert converted["npcs"][0]["notes"] == "Author-only backstory"
    assert converted["adventure"]["license_url"] == original["adventure"]["license_url"]


@pytest.mark.parametrize("key", ["session", "session_state", "chat_messages", "messages"])
def test_saved_sessions_are_not_blueprints(key):
    source = manifest()
    source[key] = {}
    with pytest.raises(CompatibilityError, match="Saved sessions"):
        export_upstream_manifest(source)


@pytest.mark.parametrize("version", ["0.9", "1.4", "2.0", "invalid"])
def test_versions_are_validated_not_blindly_rewritten(version):
    source = manifest()
    source["version"] = version
    with pytest.raises(CompatibilityError):
        import_upstream_manifest(source)


def test_flat_layout_appearance_and_legacy_format_are_normalized():
    source = manifest()
    source.update(source.pop("adventure"))
    source["version"] = "1.2"
    source["format"] = "taleweaver.adz"
    source["npcs"][0]["appearance"] = "red scarf"
    converted = import_upstream_manifest(source)
    assert converted["format"] == "TaleWeaver"
    assert converted["version"] == "1.2"
    assert "red scarf" in converted["npcs"][0]["description"]
    assert converted["adventure"]["creator"] == "Original author"


@pytest.mark.parametrize("field", ["scripts", "soft_rules"])
def test_sequence_local_semantics_require_manual_conversion(field):
    source = manifest()
    source["sequences"] = [{"id": "SEQ", field: [{"id": "CUSTOM"}]}]
    with pytest.raises(CompatibilityError, match="Sequence-local"):
        import_upstream_manifest(source)


def test_inline_interaction_semantics_are_not_misrepresented():
    source = manifest()
    source["npcs"][0]["on_interact_text"] = "Only speak when inspected"
    with pytest.raises(CompatibilityError, match="interaction semantics"):
        import_upstream_manifest(source)


def test_unknown_semantics_and_legacy_modes_block_publication():
    source = manifest()
    source["objects"][0]["custom_behavior"] = "Important puzzle rule"
    with pytest.raises(CompatibilityError, match="custom behavior"):
        export_upstream_manifest(source)
    source = manifest()
    source["adventure"]["rule_enforcement_mode"] = "strict"
    with pytest.raises(CompatibilityError, match="Choose RPG"):
        export_upstream_manifest(source)


def test_unsupported_script_api_and_malformed_script_block_conversion():
    source = manifest()
    source["scripts"][0]["code"] = "tw.npcs.give_to_player('FRIEND', 'CUP')"
    with pytest.raises(CompatibilityError, match="API unavailable"):
        import_upstream_manifest(source)
    source["scripts"][0]["code"] = "if ?"
    with pytest.raises(CompatibilityError, match="syntax"):
        export_upstream_manifest(source)


def test_script_references_to_removed_data_block_publication():
    source = manifest()
    source["objects"][0]["metadata_json"] = {"secret": "A plot clue"}
    source["scripts"][0]["code"] = "tw.narrate(tw.vars.get('secret'))"
    with pytest.raises(CompatibilityError, match="script references"):
        export_upstream_manifest(source)


def test_provenance_links_and_authored_history_are_preserved():
    source = manifest()
    source["metadata"] = {"source_url": "https://example.org/original", "original_author": "Author"}
    source["npcs"][0]["metadata_json"] = {"history": "Once lived by the sea", "hobby": "Sailing"}
    converted, report = export_upstream_manifest(source)
    assert converted["metadata"] == source["metadata"]
    assert converted["npcs"][0]["metadata_json"] == source["npcs"][0]["metadata_json"]
    assert not report.requires_acknowledgement


@pytest.mark.parametrize("key", ["metadata_json", "visual_profile", "stats"])
def test_malformed_nested_fields_fail_with_compatibility_error(key):
    source = manifest()
    source["npcs"][0][key] = ["invalid"]
    with pytest.raises(CompatibilityError, match="must be an object"):
        export_upstream_manifest(source)


def test_inbound_legacy_strict_mode_is_preserved_without_claiming_upstream_support():
    source = manifest()
    source["adventure"]["rule_enforcement_mode"] = "strict"
    assert import_upstream_manifest(source)["adventure"]["rule_enforcement_mode"] == "strict"
    with pytest.raises(CompatibilityError, match="Choose RPG"):
        export_upstream_manifest(source)


def test_inbound_unknown_behavior_requires_review():
    source = manifest()
    source["objects"][0]["custom_behavior"] = "Essential puzzle behavior"
    with pytest.raises(CompatibilityError, match="custom behavior"):
        import_upstream_manifest(source)


@pytest.mark.parametrize(
    "field, message", [("version", "release version"), ("origin_id", "stable origin ID")]
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_publication_requires_release_version_and_origin(field, message, value):
    source = manifest()
    if value is None:
        source["adventure"].pop(field)
    else:
        source["adventure"][field] = value
    with pytest.raises(CompatibilityError, match=message):
        export_upstream_manifest(source)
    assert import_upstream_manifest(source)["adventure"].get(field) == value


def test_publication_preserves_legacy_non_uuid_origin_and_release_version():
    source = manifest()
    source["adventure"]["origin_id"] = "legacy-adventure-identity"
    source["adventure"]["version"] = "2.7-beta"
    converted, report = export_upstream_manifest(source)
    assert converted["adventure"]["origin_id"] == "legacy-adventure-identity"
    assert converted["adventure"]["version"] == "2.7-beta"
    assert converted["version"] == "1.3"
    assert not report.warnings


def test_publication_requires_nonempty_title():
    source = manifest()
    source["adventure"]["title"] = "  "
    with pytest.raises(CompatibilityError, match="title is required"):
        export_upstream_manifest(source)
