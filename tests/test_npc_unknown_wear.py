"""Missing wardrobe knowledge cannot implicitly authorize removing a garment."""

from copy import deepcopy

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.narrated_items.commands import transfer
from backend.engine.visual_novel.continuity import possession_snapshot
from tests.observable_state_support import profile, world


def fixture():
    host, rows = world()
    next(row for row in rows if row.id == "npc").visual_profile = None
    return actor_records(host, rows), possession_snapshot(host, rows)


@pytest.mark.parametrize("operation", ["give", "put_down"])
def test_garment_transfer_preserves_unknown_placement_instead_of_assuming_not_worn(operation):
    actors, snapshot = fixture()
    before = deepcopy(actors), deepcopy(snapshot)
    with pytest.raises(ValueError, match="unknown"):
        transfer(actors, snapshot, "npc", "COAT", operation, recipient_id="other", detailed=False)
    assert (actors, snapshot) == before


def test_an_ordinary_legacy_possession_can_still_be_given_without_a_wardrobe_profile():
    actors, snapshot = fixture()
    changed, result, _ = transfer(
        actors, snapshot, "npc", "FLASK", "give", recipient_id="other", detailed=False
    )
    assert result.owners["FLASK"] == "other"
    assert any(row["id"] == "FLASK" for row in changed["other"]["resolved_inventory"])


def test_an_explicitly_carried_garment_with_a_valid_profile_remains_transferable():
    actors, snapshot = fixture()
    actors["npc"]["visual_profile"] = profile()
    _, result, _ = transfer(
        actors, snapshot, "npc", "COAT", "give", recipient_id="other", detailed=False
    )
    assert result.owners["COAT"] == "other"
