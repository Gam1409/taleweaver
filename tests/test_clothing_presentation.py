"""Only the player's own sheet can expose their covered clothing layers."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.clothing.presentation import player_clothing
from backend.engine.npc_journal.presentation import player_entity_view


def actor(age=27):
    return SimpleNamespace(
        visual_profile={
            "appearance": {"age_years": age, "hair": "black"},
            "worn": [{"item_id": "SHIRT"}, {"item_id": "INNER"}],
        },
        inventory=[
            {
                "id": "SHIRT",
                "name": "Blue shirt",
                "clothing": {"layer": 1, "coverage": ["torso"], "description": "Cotton shirt"},
            },
            {
                "id": "INNER",
                "name": "Private underlayer",
                "clothing": {
                    "layer": 0,
                    "coverage": ["torso"],
                    "underwear": True,
                    "description": "Plain underlayer",
                },
            },
        ],
        equipment={},
    )


def test_own_detailed_sheet_includes_covered_layers_with_visibility():
    view = player_clothing(actor(), {"clothing_settings": {"detailed": True}})
    assert [(row["item_id"], row["visible"]) for row in view["worn"]] == [
        ("SHIRT", True),
        ("INNER", False),
    ]
    assert view["appearance"]["hair"] == "black"


@pytest.mark.parametrize("age", [None, 17, 27])
def test_general_sheet_only_exposes_visible_outer_names(age):
    view = player_clothing(actor(age), {})
    assert [row["item_id"] for row in view["worn"]] == ["SHIRT"]
    assert view["worn"][0]["description"] == ""
    assert "Private" not in json.dumps(view)


@pytest.mark.parametrize("age", [None, 17])
def test_detailed_sheet_requires_explicit_adult_for_underlayers(age):
    view = player_clothing(actor(age), {"clothing_settings": {"detailed": True}})
    assert [row["item_id"] for row in view["worn"]] == ["SHIRT"]


def test_sheet_ignores_transferred_garment_and_does_not_mutate_state():
    avatar = actor()
    avatar.inventory = avatar.inventory[:1]
    before = json.dumps(avatar.visual_profile)
    view = player_clothing(avatar, {"clothing_settings": {"detailed": True}})
    assert [row["item_id"] for row in view["worn"]] == ["SHIRT"]
    assert json.dumps(avatar.visual_profile) == before


def test_legacy_sheet_does_not_invent_an_outfit():
    assert player_clothing(SimpleNamespace(), {}) is None


def test_npc_public_payload_recursively_redacts_private_visual_profile():
    profile = actor().visual_profile
    public = player_entity_view(
        {
            "entity_type": "NPC",
            "name": "Miki",
            "visual_profile": profile,
            "metadata_json": {"visual_profile": profile},
        }
    )
    assert "visual_profile" not in json.dumps(public)
    assert public["name"] == "Miki"
