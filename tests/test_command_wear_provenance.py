"""Actor commands retain current wear without inventing narration evidence."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.engine.clothing.changes import preview
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.narration import _known_placements
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.wear_provenance import remap_profile, source_matches, stamp_profile
from tests.observable_state_support import world

INPUT = "The visitor chooses a practical next step."


def proof(**changes):
    from backend.engine.clothing.body_schema import WearCommandProof

    return WearCommandProof(
        **{
            "command_id": "wear-command",
            "actor_id": "npc",
            "item_id": "COAT",
            "input_id": "input",
            "input_hash": sha256(INPUT.encode()).hexdigest(),
            "input_revision": "revision",
            "request_hash": "a" * 64,
            "operation": "adjust_clothing",
            **changes,
        }
    )


def actor():
    host, rows = world()
    return actor_records(host, rows)["npc"]


def message(**changes):
    return SimpleNamespace(
        **{
            "id": "input",
            "role": "user",
            "content": INPUT,
            "revision_id": "revision",
            "is_debug": False,
            **changes,
        }
    )


def test_fully_displaced_command_wear_survives_the_narrator_projection():
    original = actor()
    changed = preview(original, "COAT", "adjust", ["torso", "arms"], detailed=False, proof=proof())
    placements = _known_placements(changed, False)
    assert any(
        row["item_id"] == "COAT" and row["uncovered_regions"] == ["torso", "arms"]
        for row in placements
    )
    assert original["visual_profile"]["worn"] != changed["visual_profile"]["worn"]
    profile = load_profile(changed["visual_profile"])
    source = next(row.source for row in profile.worn if row.item_id == "COAT")
    assert source.source_role == "command" and source.command == proof()
    assert "evidence" not in source.model_dump()
    assert not source_matches(source.model_dump(), INPUT)


@pytest.mark.parametrize(
    "changes", [{"actor_id": "other"}, {"item_id": "OTHER"}, {"operation": "wear_item"}]
)
def test_a_command_proof_cannot_be_reused_for_another_actor_item_or_operation(changes):
    original = actor()
    before = deepcopy(original)
    with pytest.raises(ValueError, match="bound|match"):
        preview(original, "COAT", "adjust", ["arms"], detailed=False, proof=proof(**changes))
    assert original == before


def test_saved_command_proof_checks_its_input_hash_separately_from_its_request_hash():
    from backend.engine.clothing.body_schema import WearSource
    from backend.engine.clothing.wear_provenance import command_matches

    source = WearSource.from_command(proof())
    assert command_matches(source, message(), actor_id="npc", item_id="COAT")
    for changes in [
        {"content": "Edited input."},
        {"id": "other"},
        {"role": "assistant"},
        {"revision_id": "edited"},
        {"is_debug": True},
    ]:
        assert not command_matches(source, message(**changes), actor_id="npc", item_id="COAT")
    assert not command_matches(source, message(), actor_id="other", item_id="COAT")
    assert not command_matches(source, message(), actor_id="npc", item_id="OTHER")


def test_copied_command_binding_remaps_anchors_and_missing_input_preserves_the_profile():
    from backend.engine.clothing.wear_provenance import command_matches

    changed = preview(actor(), "COAT", "adjust", ["arms"], detailed=False, proof=proof())
    copied = remap_profile(changed["visual_profile"], {"input": "copied-input"})
    profile = load_profile(copied)
    source = next(row.source for row in profile.worn if row.item_id == "COAT")
    assert (
        source.source_message_id == source.request_id == source.command.input_id == "copied-input"
    )
    assert command_matches(source, message(id="copied-input"), actor_id="npc", item_id="COAT")
    missing = load_profile(remap_profile(changed["visual_profile"], {}))
    assert missing is not None and {row.item_id for row in missing.worn} == {"COAT", "LINING"}
    source = next(row.source for row in missing.worn if row.item_id == "COAT")
    assert not command_matches(source, message(), actor_id="npc", item_id="COAT")


def test_prose_stamping_does_not_relabel_a_command_as_an_assistant_quote():
    changed = preview(actor(), "COAT", "adjust", ["arms"], detailed=False, proof=proof())
    result = stamp_profile(
        changed["visual_profile"], "input", message(id="reply", role="assistant")
    )
    assert result == changed["visual_profile"]


def test_legacy_narration_source_serialization_has_no_new_null_command_field():
    from backend.engine.clothing.body_schema import WearSource

    source = WearSource(content_hash="b" * 64, evidence="A narrated placement.")
    assert source.model_dump() == {
        "request_id": None,
        "source_message_id": None,
        "content_hash": "b" * 64,
        "evidence": "A narrated placement.",
    }
    with pytest.raises(ValueError):
        WearSource(content_hash="b" * 64)


@pytest.mark.parametrize("age,detailed", [(17, True), (None, True), (30, False)])
def test_valid_command_proof_does_not_authorize_unavailable_inner_garment_detail(age, detailed):
    original = actor()
    original["visual_profile"]["appearance"]["age_years"] = age
    item = next(row for row in original["resolved_inventory"] if row["id"] == "LINING")
    item["metadata_json"]["clothing"]["underwear"] = True
    before = deepcopy(original)
    with pytest.raises(ValueError, match="unavailable"):
        preview(
            original, "LINING", "adjust", ["arms"], detailed=detailed, proof=proof(item_id="LINING")
        )
    assert original == before
