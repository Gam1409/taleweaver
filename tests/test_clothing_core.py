"""Layer visibility is deterministic, ownership-bound and conservative about unknown facts."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    reconcile_profile,
    sanitize_garment,
    sanitize_inventory,
    validate_profile,
)
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.schema import Appearance, Garment, VisualProfile


def item(identifier, layer, regions, **extra):
    return {
        "id": identifier,
        "name": f"Name {identifier}",
        "description": f"Untrusted general description for {identifier}",
        "clothing": {
            "layer": layer,
            "coverage": regions,
            "description": f"Garment detail {identifier}",
            **extra,
        },
    }


def profile(*identifiers, age=None):
    return {
        "version": 1,
        "appearance": {"age_years": age, "hair": "Black", "eyes": "Grey"},
        "worn": [{"item_id": identifier} for identifier in identifiers],
    }


def ids(result):
    return [garment["item_id"] for garment in result["clothing"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"layer": -1, "coverage": ["torso"]},
        {"layer": 5, "coverage": ["torso"]},
        {"layer": True, "coverage": ["torso"]},
        {"layer": 1, "coverage": []},
        {"layer": 1, "coverage": ["torso", "torso"]},
        {"layer": 1, "coverage": ["unknown"]},
        {"layer": 1, "coverage": ["torso"], "opaque": "false"},
        {"layer": 1, "coverage": ["torso"], "private_state": "excluded"},
    ],
)
def test_invalid_garment_contract_is_rejected(bad):
    with pytest.raises(ValidationError):
        Garment.model_validate(bad)
    assert sanitize_garment(bad) is None


def test_opaque_layers_hide_all_details_of_lower_garments():
    clothes = [
        item("INNER_SECRET", 0, ["torso"]),
        item("SHIRT", 1, ["torso"]),
        item("COAT", 3, ["torso"]),
    ]
    result = visible_character(
        profile("INNER_SECRET", "SHIRT", "COAT", age=30), clothes, detailed=True
    )
    assert ids(result) == ["COAT"]
    serialized = json.dumps(result)
    assert "INNER_SECRET" not in serialized and "SHIRT" not in serialized
    assert "Untrusted general description" not in serialized
    assert result["clothing"][0]["description"] == "Garment detail COAT"


def test_partial_coverage_only_exposes_unblocked_regions():
    clothes = [item("SHIRT", 1, ["torso", "arms"]), item("VEST", 2, ["torso"])]
    result = visible_character(profile("SHIRT", "VEST"), clothes)
    assert ids(result) == ["SHIRT", "VEST"]
    assert result["clothing"][0]["visible_regions"] == ["arms"]
    assert all(g["description"] == "" for g in result["clothing"])


def test_open_garment_changes_only_declared_coverage():
    clothes = [item("SHIRT", 1, ["torso", "arms"]), item("COAT", 3, ["torso", "arms"])]
    appearance = profile("SHIRT", "COAT")
    appearance["worn"][1]["uncovered_regions"] = ["torso"]
    result = visible_character(appearance, clothes)
    assert result["clothing"][0]["visible_regions"] == ["torso"]
    assert result["clothing"][1]["visible_regions"] == ["arms"]


def test_transparent_higher_layer_does_not_occlude_and_equal_layers_share_visibility():
    clothes = [
        item("SHIRT", 1, ["torso"]),
        item("SCARF", 1, ["torso"]),
        item("OVERLAY", 3, ["torso"], opaque=False),
    ]
    result = visible_character(profile("SHIRT", "SCARF", "OVERLAY"), clothes)
    assert ids(result) == ["SHIRT", "SCARF", "OVERLAY"]
    assert all(g["visible_regions"] == ["torso"] for g in result["clothing"])


@pytest.mark.parametrize(
    ("age", "detailed", "allowed"),
    [(None, True, False), (17, True, False), (18, True, True), (35, False, False)],
)
def test_underwear_details_require_explicit_adulthood_and_detail_opt_in(age, detailed, allowed):
    clothes = [item("UNDERLAYER", 0, ["torso"], underwear=True)]
    result = visible_character(profile("UNDERLAYER", age=age), clothes, detailed=detailed)
    assert ("UNDERLAYER" in json.dumps(result)) is allowed
    assert result["clothing_detail_limited"] is not allowed


def test_hidden_underwear_never_appears_even_for_adult_detailed_profile():
    clothes = [item("UNDERLAYER", 0, ["torso"], underwear=True), item("SHIRT", 1, ["torso"])]
    result = visible_character(profile("UNDERLAYER", "SHIRT", age=30), clothes, detailed=True)
    assert ids(result) == ["SHIRT"]
    assert "UNDERLAYER" not in json.dumps(result)


def test_detail_exclusion_does_not_make_a_covering_garment_transparent():
    clothes = [item("LOWER_SECRET", 0, ["torso"]), item("UNDERLAYER", 1, ["torso"], underwear=True)]
    result = visible_character(profile("LOWER_SECRET", "UNDERLAYER"), clothes)
    assert result["clothing"] == []
    assert result["clothing_detail_limited"] is True
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"version": 2},
        {"appearance": {"age_years": True}},
        {"appearance": {"age_years": "30"}},
    ],
)
def test_legacy_or_invalid_profile_does_not_invent_a_wardrobe(raw):
    clothes = [item("COAT", 3, ["torso"])]
    assert load_profile(raw) is None
    assert visible_character(raw, clothes, equipment={"Chest": clothes[0]}) is None
    assert reconcile_profile(raw, clothes) is None


def test_new_profile_rejects_duplicate_unowned_and_invalid_uncovered_references():
    clothes = [item("COAT", 3, ["torso"])]
    with pytest.raises(ValueError):
        validate_profile(profile("COAT", "COAT"), clothes)
    with pytest.raises(ValueError, match="belong"):
        validate_profile(profile("OTHER_OWNER"), clothes)
    with pytest.raises(ValueError, match="metadata"):
        validate_profile(profile("COAT"), [{"id": "COAT"}])
    appearance = profile("COAT")
    appearance["worn"][0]["uncovered_regions"] = ["legs"]
    with pytest.raises(ValueError, match="coverage"):
        validate_profile(appearance, clothes)
    assert visible_character(appearance, clothes)["clothing_detail_limited"] is True


def test_transfer_reconciliation_preserves_remaining_layers_without_equipping_receiver():
    shirt, coat = item("SHIRT", 1, ["torso"]), item("COAT", 3, ["torso"])
    original = profile("SHIRT", "COAT", age=24)
    before = deepcopy(original)
    remaining = reconcile_profile(original, [shirt])
    assert [g["item_id"] for g in remaining["worn"]] == ["SHIRT"]
    assert ids(visible_character(remaining, [shirt])) == ["SHIRT"]
    recipient = reconcile_profile(profile(), [coat])
    assert recipient["worn"] == []
    assert original == before


def test_unknown_owned_coverage_blocks_inner_detail_until_repaired():
    clothes = [
        item("INNER_SECRET", 0, ["torso"]),
        {"id": "UNKNOWN_COAT", "name": "Unspecified coat"},
    ]
    appearance = reconcile_profile(profile("INNER_SECRET", "UNKNOWN_COAT"), clothes)
    assert len(appearance["worn"]) == 2
    result = visible_character(appearance, clothes, detailed=True)
    assert result["clothing"] == [] and result["clothing_detail_limited"] is True
    assert "INNER_SECRET" not in json.dumps(result)


def test_equipment_and_worn_share_ids_without_duplication_or_stale_ownership():
    coat = item("COAT", 3, ["torso"])
    equipment = {"Chest": "COAT", "Arms": coat, "Head": "LOST_HAT"}
    result = visible_character(profile("COAT"), [coat], equipment=equipment)
    assert ids(result) == ["COAT"]
    assert set(owned_items([coat], equipment=equipment)) == {"COAT"}
    assert ids(visible_character(profile(), [], equipment={"Chest": coat})) == ["COAT"]


def test_ambiguous_inventory_definition_is_not_used_to_expose_lower_layers():
    coat = item("COAT", 3, ["torso"])
    duplicate = {**coat, "clothing": {**coat["clothing"], "opaque": False}}
    clothes = [item("INNER_SECRET", 0, ["torso"]), coat, duplicate]
    result = visible_character(profile("INNER_SECRET", "COAT"), clothes, detailed=True)
    assert result["clothing_detail_limited"] is True and result["clothing"] == []


def test_metadata_garment_is_supported_and_inventory_sanitizing_is_nonmutating():
    coat = item("COAT", 3, ["torso"])
    coat["metadata_json"] = {"clothing": coat.pop("clothing"), "other": "retained"}
    invalid = {"id": "BROKEN", "name": "Broken", "clothing": {"coverage": ["unknown"]}}
    source = [coat, invalid, "LINKED_ITEM", {"name": "Legacy possession without an ID"}]
    before = deepcopy(source)
    sanitized = sanitize_inventory(source)
    assert source == before
    assert garment_for_item(sanitized[0]).layer == 3
    assert "clothing" not in sanitized[1] and sanitized[1]["id"] == "BROKEN"
    assert sanitized[2] == "LINKED_ITEM"
    assert sanitized[3] == {"name": "Legacy possession without an ID"}
    assert ids(visible_character(profile("COAT"), sanitized)) == ["COAT"]


def test_invalid_canonical_clothing_does_not_revive_conflicting_legacy_metadata():
    coat = item("COAT", 3, ["torso"])
    coat["metadata_json"] = {"clothing": coat["clothing"]}
    coat["clothing"] = {"layer": 0, "coverage": ["invalid"]}
    sanitized = sanitize_inventory([coat])
    assert garment_for_item(sanitized[0]) is None
    assert visible_character(profile("COAT"), sanitized)["clothing_detail_limited"] is True


def test_only_known_visual_fields_survive_projection():
    raw = VisualProfile(appearance=Appearance(age_years=30, hair="Brown")).model_dump()
    inventory = [{**item("COAT", 2, ["torso"]), "private_state": "SECRET"}]
    raw["worn"] = [{"item_id": "COAT"}]
    result = visible_character(raw, inventory, detailed=True)
    assert "SECRET" not in json.dumps(result)
    assert set(result) == {"appearance", "clothing", "clothing_detail_limited"}
    assert set(result["clothing"][0]) == {"item_id", "name", "description", "visible_regions"}


def test_malformed_item_name_is_not_stringified_into_visual_output():
    coat = item("COAT", 3, ["torso"])
    coat["name"] = {"private": "SECRET"}
    result = visible_character(profile("COAT"), [coat], detailed=True)
    assert result["clothing"][0]["name"] == ""
    assert "SECRET" not in json.dumps(result)
